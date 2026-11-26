"""Admin-Seite „Dateien“: sichten, unbenutzte löschen, umbenennen; Aufräumen beim Ersetzen (Issue #22)."""
import os
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from app.models import Levels, Questions_Catalogs, Questions_GroupExercise, Questions_Practical
from .models import EditLogEntry
from .tests import grant


class FilesTestBase(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.admin = User.objects.create_user('admin')
        grant(self.admin, 'access_admin', 'manage_files', 'manage_practical', 'manage_group_exercises')
        self.client.force_login(self.admin)
        self.level = Levels.objects.create(name='Bronze', slug='bronze-f', order=70)
        self.catalog = Questions_Catalogs.objects.create(title='Leinen', level=self.level)
        self.used = default_storage.save('Aufgaben-Praktisch/knoten.pdf', ContentFile(b'%PDF used'))
        self.unused = default_storage.save('Aufgaben-Praktisch/alt.pdf', ContentFile(b'%PDF old'))
        self.task = Questions_Practical.objects.create(question='Knoten', catalog=self.catalog, number='1',
                                                       file=self.used)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)


class FilesPageTests(FilesTestBase):
    def test_requires_own_permission(self):
        other = User.objects.create_user('other')
        grant(other, 'access_admin', 'manage_practical', 'manage_settings')
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse('admin_files')).status_code, 403)
        self.assertEqual(self.client.post(reverse('admin_files_delete'), {'names': [self.unused]}).status_code, 403)
        self.assertTrue(default_storage.exists(self.unused))

    def test_lists_files_with_usage(self):
        default_storage.save('tmp/abc123/vergessen.pdf', ContentFile(b'x'))
        response = self.client.get(reverse('admin_files'))
        files = {f['name']: f for f in response.context['files']}
        self.assertTrue(files[self.used]['used'])
        self.assertFalse(files[self.unused]['used'])
        self.assertTrue(files['tmp/abc123/vergessen.pdf']['temp'])
        self.assertEqual(response.context['unused_count'], 2)
        self.assertContains(response, reverse('admin_practical_edit', args=[self.catalog.pk, self.task.pk]))
        only_unused = self.client.get(reverse('admin_files'), {'status': 'unbenutzt'}).context['files']
        self.assertNotIn(self.used, [f['name'] for f in only_unused])

    def test_delete_only_unused(self):
        default_storage.save('tmp/abc123/vergessen.pdf', ContentFile(b'x'))
        self.client.post(reverse('admin_files_delete'),
                         {'names': [self.unused, self.used, 'tmp/abc123/vergessen.pdf']})
        self.assertFalse(default_storage.exists(self.unused))
        self.assertTrue(default_storage.exists(self.used))
        self.assertFalse(os.path.exists(os.path.join(self.media, 'tmp', 'abc123')))  # leerer tmp-Ordner weg
        self.assertEqual(EditLogEntry.objects.filter(target_type='file', action='delete').count(), 2)

    def test_path_traversal_is_rejected(self):
        outside = os.path.join(os.path.dirname(self.media), 'geheim.txt')
        with open(outside, 'w') as handle:
            handle.write('x')
        try:
            for name in ('../geheim.txt', os.path.abspath(outside), 'Aufgaben-Praktisch/../../geheim.txt'):
                self.client.post(reverse('admin_files_delete'), {'names': [name]})
                self.client.post(reverse('admin_file_rename'), {'name': name, 'new_name': 'neu'})
            self.assertTrue(os.path.exists(outside))
            self.assertFalse(os.path.exists(os.path.join(self.media, 'neu')))
        finally:
            os.remove(outside)

    def test_rename_updates_references(self):
        group = Questions_GroupExercise.objects.create(question='Gruppe', number='G1', file=self.used)
        response = self.client.post(reverse('admin_file_rename'), {'name': self.used, 'new_name': 'Mastwurf binden'})
        self.assertEqual(response.status_code, 302)
        new_name = 'Aufgaben-Praktisch/Mastwurf_binden.pdf'
        self.assertTrue(default_storage.exists(new_name))
        self.assertFalse(default_storage.exists(self.used))
        self.task.refresh_from_db()
        group.refresh_from_db()
        self.assertEqual((self.task.file.name, group.file.name), (new_name, new_name))
        entry = EditLogEntry.objects.get(action='rename')
        self.assertEqual(entry.changes['Name'], [self.used, new_name])

    def test_rename_refuses_existing_name_and_keeps_extension(self):
        self.client.post(reverse('admin_file_rename'), {'name': self.used, 'new_name': 'alt.pdf'})
        self.task.refresh_from_db()
        self.assertEqual(self.task.file.name, self.used)  # Ziel gibt es schon: unverändert
        self.client.post(reverse('admin_file_rename'), {'name': self.unused, 'new_name': 'neu.exe'})
        self.assertTrue(default_storage.exists('Aufgaben-Praktisch/neu.exe.pdf'))  # Endung bleibt


class FileCleanupTests(FilesTestBase):
    def test_replaced_task_file_is_removed_if_unused(self):
        self.client.post(reverse('admin_practical_edit', args=[self.catalog.pk, self.task.pk]), {
            'number': '1', 'question': 'Knoten', 'help_reference': '',
            'file': SimpleUploadedFile('neu.pdf', b'%PDF new', content_type='application/pdf'),
        })
        self.task.refresh_from_db()
        self.assertEqual(self.task.file.name, 'Aufgaben-Praktisch/neu.pdf')
        self.assertFalse(default_storage.exists(self.used))

    def test_shared_file_survives_replace_and_delete(self):
        group = Questions_GroupExercise.objects.create(question='Gruppe', number='G1', file=self.used)
        self.task.delete()  # andere Art nutzt die Datei noch
        self.assertTrue(default_storage.exists(self.used))
        group.delete()
        self.assertFalse(default_storage.exists(self.used))

    def test_shared_level_icon_is_kept(self):
        icon = default_storage.save('levels/logo.webp', ContentFile(b'RIFF'))
        a = Levels.objects.create(name='A', slug='a-f', order=71)
        b = Levels.objects.create(name='B', slug='b-f', order=72)
        Levels.objects.filter(pk__in=[a.pk, b.pk]).update(icon=icon)
        Levels.objects.get(pk=a.pk).delete()
        self.assertTrue(default_storage.exists(icon))
