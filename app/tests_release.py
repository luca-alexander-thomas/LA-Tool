"""Version aus release.json (vom Deploy-Workflow geschrieben): Anzeige, Notizen, Health-Check."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from app import release


class ReleaseTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'release.json'
        patcher = patch.object(release, 'RELEASE_FILE', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        release.current_release.cache_clear()
        self.addCleanup(release.current_release.cache_clear)

    def write(self, **data):
        self.path.write_text(json.dumps(data), encoding='utf-8')
        release.current_release.cache_clear()

    def test_without_file_no_version(self):
        self.assertIsNone(release.current_release())
        self.assertIsNone(self.client.get(reverse('health')).json()['version'])
        self.assertContains(self.client.get(reverse('release_notes')), 'Entwicklungsstand')
        self.assertNotContains(self.client.get(reverse('legal_imprint')), 'Version ')

    def test_version_in_footer_health_and_notes(self):
        self.write(tag='v1.2.0', name='Herbst-Update', body='## Neu\n- **Sammelaktionen** im Katalog\n- `Filter` bleiben\n\nMehr: https://github.com/x/y/pull/3',
                   published_at='2026-11-12T10:00:00Z', url='https://github.com/x/y/releases/tag/v1.2.0')
        self.assertEqual(self.client.get(reverse('health')).json()['version'], 'v1.2.0')
        self.assertContains(self.client.get(reverse('legal_imprint')), 'Version v1.2.0')
        html = self.client.get(reverse('release_notes')).content.decode()
        self.assertIn('Herbst-Update', html)
        self.assertIn('<h2>Neu</h2>', html)
        self.assertIn('<li><strong>Sammelaktionen</strong> im Katalog</li>', html)
        self.assertIn('<code>Filter</code>', html)
        self.assertIn('href="https://github.com/x/y/pull/3"', html)
        self.assertIn('12. November 2026', html)

    def test_notes_are_escaped(self):
        html = release.notes_html('<script>alert(1)</script>\n- [x](javascript:alert(1))\n- <img src=x onerror=alert(1)>')
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('href="javascript', html)
        self.assertIn('&lt;script&gt;', html)

    def test_foreign_url_dropped_and_broken_file(self):
        self.write(tag='v1', url='https://evil.example/')
        self.assertEqual(release.current_release()['url'], '')
        self.path.write_text('{kaputt', encoding='utf-8')
        release.current_release.cache_clear()
        self.assertIsNone(release.current_release())

    def test_home_hint_for_logged_in(self):
        self.write(tag='v2.0.0')
        user = User.objects.create_user('jugend')
        self.client.force_login(user)
        session = self.client.session
        session['first_run_done'] = True
        session.save()
        self.assertContains(self.client.get(reverse('home')), 'Neu in Version v2.0.0')
