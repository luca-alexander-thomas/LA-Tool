"""Änderungsprotokoll für Stammdaten (Issue #16)."""
import json
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Levels, Questions_Catalogs, Questions_Practical, Questions_Theory, Work
from .edit_log import diff, log_edit, snapshot
from .models import EditLogEntry
from .tests import grant


class EditLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin', first_name='Ada', last_name='Admin')
        grant(self.admin, 'access_admin', 'manage_catalogs', 'manage_theory', 'manage_practical')
        self.client.force_login(self.admin)
        self.level = Levels.objects.create(name='Bronze', slug='bronze-l', order=60)
        self.catalog = Questions_Catalogs.objects.create(title='Leinen', short_title='L1', level=self.level)

    def test_update_records_person_and_field_changes(self):
        self.client.post(reverse('admin_catalog_update', args=[self.catalog.pk]), {
            'title': 'Leinen und Knoten', 'short_title': 'L1', 'level': self.level.pk, 'order': 0,
            'multi_answer_scoring': self.catalog.multi_answer_scoring,
        })
        entry = EditLogEntry.objects.get()
        self.assertEqual((entry.user, entry.user_name, entry.action, entry.target_type, entry.target_id),
                         (self.admin, 'Ada Admin', 'update', 'catalog', self.catalog.pk))
        self.assertEqual(entry.changes['title'], ['Leinen', 'Leinen und Knoten'])
        self.assertNotIn('short_title', entry.changes)

    def test_form_edit_keeps_old_values(self):
        """Das ModelForm schreibt schon bei is_valid() ins Objekt – der Vorher-Stand muss davor stehen."""
        task = Questions_Practical.objects.create(question='Knoten', catalog=self.catalog, number='1')
        self.client.post(reverse('admin_practical_edit', args=[self.catalog.pk, task.pk]),
                         {'number': '2', 'question': 'Knoten binden', 'help_reference': ''})
        entry = EditLogEntry.objects.get()
        self.assertEqual(entry.changes['question'], ['Knoten', 'Knoten binden'])
        self.assertEqual(entry.changes['number'], ['1', '2'])

    def test_create_delete_and_bulk(self):
        self.client.post(reverse('admin_theory_create', args=[self.catalog.pk]), {
            'number': '1', 'question': 'Wofür?', 'help_reference': '', 'choice': ['Ja', 'Nein'], 'correct': ['0'],
        })
        question = Questions_Theory.objects.get()
        self.client.post(reverse('admin_catalog_bulk', args=[self.catalog.pk]),
                         {'kind': 'theory', 'action': 'draft', 'ids': [str(question.pk)]})
        self.client.post(reverse('admin_theory_delete', args=[self.catalog.pk, question.pk]))
        actions = list(EditLogEntry.objects.order_by('pk').values_list('action', 'target_type'))
        self.assertEqual(actions, [('create', 'theory'), ('bulk', 'catalog'), ('delete', 'theory')])
        bulk = EditLogEntry.objects.get(action='bulk')
        self.assertEqual(bulk.changes['Sammelaktion'], ['', '1 Frage als Entwurf markiert'])

    def test_hint_for_admins_and_log_link_only_with_permission(self):
        log_edit(self.admin, self.catalog, 'update', {'title': ['a', 'b']})
        url = reverse('admin_catalog_detail', args=[self.catalog.pk])
        html = self.client.get(url).content.decode()
        self.assertIn('Zuletzt bearbeitet von', html)
        self.assertIn('Ada Admin', html)
        self.assertNotIn(reverse('admin_edit_log'), html)  # weder Link noch Menüpunkt ohne Recht
        grant(self.admin, 'view_edit_log')
        html = self.client.get(url).content.decode()
        self.assertIn(f"{reverse('admin_edit_log')}?typ=catalog&amp;id={self.catalog.pk}", html)

    def test_log_page_requires_permission_superuser_always(self):
        log_edit(self.admin, self.catalog, 'update', {'title': ['a', 'b']})
        self.assertEqual(self.client.get(reverse('admin_edit_log')).status_code, 403)
        boss = User.objects.create_superuser('chef', password='x')
        self.client.force_login(boss)
        response = self.client.get(reverse('admin_edit_log'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Leinen')
        self.assertContains(response, reverse('admin_catalog_detail', args=[self.catalog.pk]))

    def test_log_page_filters(self):
        grant(self.admin, 'view_edit_log')
        other = Questions_Catalogs.objects.create(title='Wasser', level=self.level)
        log_edit(self.admin, self.catalog, 'update', {'title': ['a', 'b']})
        log_edit(self.admin, other, 'delete')
        response = self.client.get(reverse('admin_edit_log'), {'typ': 'catalog', 'id': other.pk})
        self.assertEqual([r['entry'].target_label for r in response.context['rows']], ['Wasser'])
        response = self.client.get(reverse('admin_edit_log'), {'aktion': 'update'})
        self.assertEqual([r['entry'].target_label for r in response.context['rows']], [str(self.catalog)])

    def test_retention_account_deletion_and_export(self):
        old = log_edit(self.admin, self.catalog, 'update', {'title': ['a', 'b']})
        EditLogEntry.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2 * 365 + 1))
        recent = log_edit(self.admin, self.catalog, 'update', {'title': ['b', 'c']})

        export = json.loads(self.client.get(reverse('my_data_export')).content)
        self.assertEqual(len(export['aenderungsprotokoll']), 2)

        call_command('cleanup_data', stdout=StringIO())
        self.assertEqual(list(EditLogEntry.objects.values_list('pk', flat=True)), [recent.pk])

        self.admin.delete()  # Name bleibt bis zum Ende der Aufbewahrung, Verknüpfung entfällt
        recent.refresh_from_db()
        self.assertEqual((recent.user, recent.user_name), (None, 'Ada Admin'))


class GroupAndSyncLogTests(TestCase):
    def test_group_permissions_change_is_logged(self):
        admin = User.objects.create_user('admin')
        grant(admin, 'access_admin', 'manage_groups')
        self.client.force_login(admin)
        group = Group.objects.create(name='Betreuer')
        self.client.post(reverse('admin_autogroup_edit', args=[group.pk]), {
            'group_name': 'Betreuer', 'entra_group_ids_text': '', 'perms': ['access_admin'],
        })
        entry = EditLogEntry.objects.get()
        self.assertEqual((entry.target_type, entry.action), ('autogroup', 'update'))
        self.assertEqual(entry.changes['permissions'], ['', 'Admin-Bereich zugreifen'])

    def test_divera_sync_logs_only_real_changes(self):
        from app.management.commands import sync_divera
        event = {'title': 'Übungsdienst', 'start': 1767268800, 'address': 'Wache', 'group': []}
        payload = {'success': True, 'data': {'ucr': {'1': {'cluster_id': 20369}},
                                             'cluster': {'group': {'5': {'name': 'Jugend'}}}}}

        def run(title):
            event['title'] = title
            with patch.object(sync_divera.Command, '_find_events', return_value={'77': dict(event)}),                     patch.object(sync_divera, '_divera_pull', return_value=payload),                     patch('la_tool.env.DIVERA_ADMIN_USER_API_KEY', 'key', create=True),                     patch('la_tool.env.DIVERA_Site_ID', '20369', create=True),                     patch('la_tool.env.DIVERA_EVENTS_GROUP', 'Jugend', create=True):
                call_command('sync_divera', stdout=StringIO(), stderr=StringIO())

        run('Übungsdienst')
        run('Übungsdienst')  # unverändert: kein weiterer Eintrag
        run('Übungsdienst Knoten')
        self.assertEqual(Work.objects.count(), 1)
        entries = list(EditLogEntry.objects.order_by('pk').values_list('action', 'user_name'))
        self.assertEqual(entries, [('create', 'Divera-Abgleich'), ('update', 'Divera-Abgleich')])
        self.assertEqual(EditLogEntry.objects.first().changes, {'title': ['Übungsdienst', 'Übungsdienst Knoten']})


class SnapshotTests(TestCase):
    def test_snapshot_and_diff(self):
        level = Levels.objects.create(name='Silber', slug='silber-s', order=61)
        before = snapshot(level)
        level.default_exam_pass_pct = 60
        level.is_draft = True
        changes = diff(before, snapshot(level))
        self.assertEqual(changes, {'default_exam_pass_pct': ['75', '60'], 'is_draft': ['nein', 'ja']})
