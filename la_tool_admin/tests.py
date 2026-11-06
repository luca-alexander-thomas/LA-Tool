import io
import json
from datetime import timedelta

import openpyxl
from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Exams, Levels, Questions_Catalogs, Questions_Theory, Work

from .models import AutoGroupRule, Profile
from .utils import sync_auto_groups
from .views import _is_truthy, _parse_import_file


def grant(user, *codenames):
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(content_type__app_label='app', codename=codename))
    return User.objects.get(pk=user.pk)  # Berechtigungs-Cache leeren


class AdminAccessTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='helfer', password='geheim-123')
        Profile.objects.create(user=self.user, divera_api_key='test-key')

    def test_anonymous_is_redirected_to_login(self):
        response = self.client.get(reverse('admin_index'))
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_user_without_permission_is_redirected_home(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('admin_index'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_permission_required_views_return_403(self):
        self.client.force_login(self.user)
        for name in ('admin_users', 'admin_catalog_create', 'admin_exam_create', 'admin_import_questions'):
            with self.subTest(view=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_user_with_access_admin_permission(self):
        user = grant(self.user, 'access_admin')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('admin_index')).status_code, 200)
        # access_admin allein reicht nicht für die Nutzerverwaltung
        self.assertEqual(self.client.get(reverse('admin_users')).status_code, 403)


class AdminPagesTests(TestCase):
    """Alle Admin-Seiten müssen für einen Superuser fehlerfrei rendern."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin', password='geheim-123')
        Profile.objects.create(user=self.admin, divera_api_key='test-key')
        self.client.force_login(self.admin)

        self.level = Levels.objects.create(name='LA Bronze', slug='bronze', order=1)
        self.catalog = Questions_Catalogs.objects.create(title='Katalog', short_title='K', level=self.level)
        self.question = Questions_Theory.objects.create(
            question='Frage?', catalog=self.catalog, answer_text='A',
            answer_correct=['A'], answer_choice=['A', 'B'],
        )
        self.exam = Exams.objects.create(name='Prüfung', level=self.level, catalog=self.catalog, time_in_min=30)
        self.work = Work.objects.create(title='Dienst', date=timezone.now() + timedelta(days=1), level=self.level)
        self.group = Group.objects.create(name='Jugend')
        self.rule = AutoGroupRule.objects.create(group=self.group, divera_qual_ids=[30132])

    def test_pages_render(self):
        urls = [
            reverse('admin_index'),
            reverse('admin_import_questions'),
            reverse('admin_catalog'),
            reverse('admin_catalog_create'),
            reverse('admin_catalog_detail', args=[self.catalog.pk]),
            reverse('admin_theory_create', args=[self.catalog.pk]),
            reverse('admin_theory_edit', args=[self.catalog.pk, self.question.pk]),
            reverse('admin_practical_create', args=[self.catalog.pk]),
            reverse('admin_group_create', args=[self.catalog.pk]),
            reverse('admin_users'),
            reverse('admin_exam_list'),
            reverse('admin_exam_create'),
            reverse('admin_exam_edit', args=[self.exam.pk]),
            reverse('admin_exam_results', args=[self.exam.pk]),
            reverse('admin_settings'),
            reverse('admin_level_list'),
            reverse('admin_level_create'),
            reverse('admin_level_edit', args=[self.level.pk]),
            reverse('admin_autogroup_list'),
            reverse('admin_autogroup_create'),
            reverse('admin_autogroup_edit', args=[self.group.pk]),
            reverse('admin_work_list'),
            reverse('admin_work_create'),
            reverse('admin_work_edit', args=[self.work.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_import_examples_download(self):
        for fmt in ('csv', 'json', 'xlsx'):
            with self.subTest(fmt=fmt):
                response = self.client.get(reverse('admin_import_example', args=[fmt]))
                self.assertEqual(response.status_code, 200)
                self.assertIn('attachment', response.get('Content-Disposition', ''))

    def test_exam_toggle(self):
        self.assertFalse(self.exam.visible)
        response = self.client.post(reverse('admin_exam_toggle', args=[self.exam.pk, 'visible']))
        self.assertRedirects(response, reverse('admin_exam_list'), fetch_redirect_response=False)
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.visible)

    def test_exam_toggle_ignores_unknown_field(self):
        self.client.post(reverse('admin_exam_toggle', args=[self.exam.pk, 'name']))
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.name, 'Prüfung')

    def test_exam_toggle_requires_post(self):
        self.client.get(reverse('admin_exam_toggle', args=[self.exam.pk, 'visible']))
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.visible)

    def test_draft_toggle(self):
        self.client.post(reverse('admin_draft_toggle', args=['catalog', self.catalog.pk]))
        self.catalog.refresh_from_db()
        self.assertTrue(self.catalog.is_draft)

    def test_draft_toggle_unknown_model(self):
        response = self.client.post(reverse('admin_draft_toggle', args=['unbekannt', 1]))
        self.assertRedirects(response, reverse('admin_index'), fetch_redirect_response=False)

    def test_draft_toggle_checks_model_permission(self):
        user = User.objects.create_user(username='redakteur')
        user = grant(user, 'access_admin')
        self.client.force_login(user)
        response = self.client.post(reverse('admin_draft_toggle', args=['catalog', self.catalog.pk]))
        self.assertEqual(response.status_code, 403)
        self.catalog.refresh_from_db()
        self.assertFalse(self.catalog.is_draft)


class ImportParserTests(TestCase):
    def test_is_truthy(self):
        for value in (True, 'x', 'X', 'ja', '1', 'true', ' Wahr ', 1):
            with self.subTest(value=value):
                self.assertTrue(_is_truthy(value))
        for value in (None, False, '', '0', 'nein', 'no'):
            with self.subTest(value=value):
                self.assertFalse(_is_truthy(value))

    def test_parse_csv(self):
        content = (
            'Nr;Frage;A;B;C;Lösung A;Lösung B;Lösung C;Hinweis\n'
            '1.1;Wofür steht THW?;Technisches Hilfswerk;Technik;Hilfe;x;;;Grundwissen\n'
            '1.2;Mehrfach?;Eins;Zwei;Drei;ja;ja;;\n'
        ).encode('utf-8-sig')
        rows = _parse_import_file(io.BytesIO(content), 'fragen.csv')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0], {
            'number': '1.1',
            'question': 'Wofür steht THW?',
            'choices': ['Technisches Hilfswerk', 'Technik', 'Hilfe'],
            'correct': ['Technisches Hilfswerk'],
            'help': 'Grundwissen',
        })
        self.assertEqual(rows[1]['correct'], ['Eins', 'Zwei'])

    def test_parse_legacy_csv(self):
        content = 'Nr;Frage;Antwort_1;Antwort_2;Korrekt\n7;Alt?;Ja;Nein;Ja\n'.encode()
        rows = _parse_import_file(io.BytesIO(content), 'alt.CSV')
        self.assertEqual(rows[0]['choices'], ['Ja', 'Nein'])
        self.assertEqual(rows[0]['correct'], ['Ja'])

    def test_parse_json(self):
        data = [
            {'number': '2', 'question': 'Index?', 'choices': ['A', 'B', 'C'], 'correct': [0, 2], 'help': 'h'},
            {'nummer': '3', 'frage': 'Text?', 'answers': ['X', 'Y'], 'korrekt': 'Y'},
        ]
        rows = _parse_import_file(io.BytesIO(json.dumps(data).encode()), 'fragen.json')
        self.assertEqual(rows[0]['correct'], ['A', 'C'])
        self.assertEqual(rows[0]['help'], 'h')
        self.assertEqual(rows[1]['number'], '3')
        self.assertEqual(rows[1]['question'], 'Text?')
        self.assertEqual(rows[1]['correct'], ['Y'])

    def test_parse_xlsx(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(['Nr', 'Frage', 'A', 'B', 'Lösung A', 'Lösung B', 'Hinweis'])
        ws.append(['5', 'Excel?', 'Ja', 'Nein', None, 'x', 'Tabelle'])
        ws.append([None, None, None, None, None, None, None])  # Leerzeile wird übersprungen
        buffer = io.BytesIO()
        wb.save(buffer)
        rows = _parse_import_file(io.BytesIO(buffer.getvalue()), 'fragen.xlsx')
        self.assertEqual(rows, [{
            'number': '5',
            'question': 'Excel?',
            'choices': ['Ja', 'Nein'],
            'correct': ['Nein'],
            'help': 'Tabelle',
        }])


class SyncAutoGroupsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='helfer')
        self.bronze = Group.objects.create(name='Bronze')
        self.leitung = Group.objects.create(name='Leitung')
        self.alle = Group.objects.create(name='Alle')
        AutoGroupRule.objects.create(group=self.bronze, divera_qual_ids=[30132])
        AutoGroupRule.objects.create(group=self.leitung, entra_group_ids=['ABC-123'])
        AutoGroupRule.objects.create(group=self.alle)  # leere Regel wird ignoriert

    def groups(self):
        return set(self.user.groups.values_list('name', flat=True))

    def test_divera_qualification_adds_group(self):
        sync_auto_groups(self.user, divera_qual_ids=[30132])
        self.assertEqual(self.groups(), {'Bronze'})

    def test_entra_group_is_case_insensitive(self):
        sync_auto_groups(self.user, entra_group_ids=['abc-123'])
        self.assertEqual(self.groups(), {'Leitung'})

    def test_lost_qualification_removes_group(self):
        sync_auto_groups(self.user, divera_qual_ids=[30132])
        sync_auto_groups(self.user, divera_qual_ids=[])
        self.assertEqual(self.groups(), set())

    def test_empty_rule_does_not_touch_membership(self):
        self.user.groups.add(self.alle)
        sync_auto_groups(self.user)
        self.assertEqual(self.groups(), {'Alle'})


class ProfileTests(TestCase):
    def setUp(self):
        self.profile = Profile.objects.create(user=User.objects.create_user(username='helfer'))

    def test_without_qualifications(self):
        self.assertIsNone(self.profile.divera_la_level)
        self.assertIsNone(self.profile.divera_la_display)
        self.assertEqual(self.profile.divera_qualification_details, [])

    def test_highest_la_level_wins(self):
        self.profile.divera_qualifications = [30132, 30134, 30133]
        self.assertEqual(self.profile.divera_la_level, 'gold')
        self.assertEqual(self.profile.divera_la_display, 'LA Gold')

    def test_qualification_details(self):
        self.profile.divera_qualifications = [24131, 99999]
        self.assertEqual(self.profile.divera_qualification_details, [
            {'id': 24131, 'name': 'Jugendhelfer', 'shortname': 'JHE'},
            {'id': 99999, 'name': 'Qual #99999', 'shortname': '?'},
        ])
