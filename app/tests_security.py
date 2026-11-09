"""Sicherheits-Regressionstests aus dem Audit (Login-Sperre, Entra-Zuordnung, Prüfungs-Integrität, Import)."""
import json
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from la_tool_admin.models import Profile
from la_tool_admin.push import safe_internal_url

from .models import ExamAttempt, ExamResultData, Exams, Levels, Questions_Catalogs, Questions_Theory, TrainingResultData


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_blocks_after_five_failures_per_username(self):
        with mock.patch('app.views.login_func.login', return_value=None):
            for _ in range(5):
                self.client.post(reverse('login'), {'username': 'Max', 'password': 'falsch'})
            response = self.client.post(reverse('login'), {'username': 'max', 'password': 'falsch'})
        self.assertContains(response, 'Zu viele fehlgeschlagene', status_code=429)

    def test_success_resets_counter(self):
        user = User.objects.create_user('max')
        with mock.patch('app.views.login_func.login', return_value=None):
            for _ in range(4):
                self.client.post(reverse('login'), {'username': 'max', 'password': 'x'})
        with mock.patch('app.views.login_func.login', return_value=user):
            self.client.post(reverse('login'), {'username': 'max', 'password': 'richtig'})
        self.client.logout()
        with mock.patch('app.views.login_func.login', return_value=None):
            response = self.client.post(reverse('login'), {'username': 'max', 'password': 'x'})
        self.assertEqual(response.status_code, 200)


@override_settings(MICROSOFT_AUTH_TENANT_ID='11111111-1111-1111-1111-111111111111')
class EntraLinkingTests(TestCase):
    def test_refuses_foreign_tenant_and_guests(self):
        from la_tool_admin.views import _entra_refusal
        own = {'tid': '11111111-1111-1111-1111-111111111111'}
        self.assertIsNone(_entra_refusal(own, {'userPrincipalName': 'max@thw-jugend-ge.de'}))
        self.assertIsNotNone(_entra_refusal({'tid': 'andere'}, {'userPrincipalName': 'max@thw-jugend-ge.de'}))
        self.assertIsNotNone(_entra_refusal(own, {'userPrincipalName': 'max_gmail.com#EXT#@thwjugend.onmicrosoft.com'}))

    def test_matches_by_entra_id_first_and_mail_case_insensitive(self):
        from la_tool_admin.views import _entra_user
        linked = User.objects.create_user('alt@thw-jugend-ge.de')
        Profile.objects.create(user=linked, entra_oid='oid-1')
        self.assertEqual(_entra_user('oid-1', 'neu@thw-jugend-ge.de', '', ''), linked)
        existing = User.objects.create_user('Max@THW-Jugend-GE.de')
        self.assertEqual(_entra_user('oid-2', 'max@thw-jugend-ge.de', '', ''), existing)


class SafeUrlTests(TestCase):
    def test_only_local_paths(self):
        self.assertEqual(safe_internal_url('/pruefungen/'), '/pruefungen/')
        for bad in ('//evil.example/', '/\\evil.example/', 'https://evil.example/', None):
            self.assertEqual(safe_internal_url(bad), '/')


class ExamIntegrityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jugend')
        self.client.force_login(self.user)
        # Ordnungszahlen über den Stufen aus den Migrationen (Bronze/Silber/Gold)
        level = Levels.objects.create(name='S', slug='s', order=901)
        Levels.objects.create(name='S2', slug='s2', order=902)
        catalog = Questions_Catalogs.objects.create(title='K', short_title='K', level=level)
        self.q = Questions_Theory.objects.create(question='F', catalog=catalog, answer_text='Ja', answer_choice=['Ja', 'Nein'])
        self.exam = Exams.objects.create(name='P', level=level, time_in_min=30, visible=True, closed=False, pass_threshold=1)
        self.exam.assigned_users.add(self.user)
        self.exam.questions.add(self.q)
        ExamAttempt.objects.create(user=self.user, exam=self.exam, question_ids=[self.q.pk],
                                   answers={str(self.q.pk): ['a']}, started_at=timezone.now())
        self.run = reverse('exam_run', args=[self.exam.pk])

    def test_lookup_training_and_offline_data_locked_during_exam(self):
        self.assertRedirects(self.client.get(reverse('theory_lookup')), self.run, fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('training_config')), self.run, fetch_redirect_response=False)
        self.assertRedirects(self.client.get(reverse('training_today')), self.run, fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('theory_offline_data')).status_code, 403)

    def test_closing_exam_ends_running_attempt_with_last_autosave(self):
        self.exam.closed = True
        self.exam.save()
        save = self.client.post(self.run, {'action': 'save', 'answers': json.dumps({str(self.q.pk): ['b']})})
        self.assertEqual(save.status_code, 409)
        self.client.post(self.run, {'answers': json.dumps({str(self.q.pk): ['b']})})
        result = ExamResultData.objects.get()
        self.assertEqual(result.answers, {str(self.q.pk): ['a']})  # gesendete Änderung zählt nicht mehr
        self.assertFalse(ExamAttempt.objects.exists())

    def test_level_advances_only_after_release(self):
        self.client.post(self.run, {'answers': json.dumps({str(self.q.pk): ['a']})})
        self.client.get(reverse('exam_result', args=[self.exam.pk]))
        self.assertNotEqual(self.client.session.get('la_filter'), 's2')
        ExamResultData.objects.update(state='published')
        self.client.get(reverse('exam_result', args=[self.exam.pk]))
        self.assertEqual(self.client.session.get('la_filter'), 's2')


class AnonymousLateSubmitTests(TestCase):
    def test_anonymous_cannot_store_results(self):
        level = Levels.objects.create(name='S', slug='s', order=1)
        catalog = Questions_Catalogs.objects.create(title='K', short_title='K', level=level)
        q = Questions_Theory.objects.create(question='F', catalog=catalog, answer_text='Ja', answer_choice=['Ja', 'Nein'])
        self.client.post(reverse('training_run'), {'run_id': 'x', 'question_ids': json.dumps([q.pk]), 'answers': '{}'})
        self.assertFalse(TrainingResultData.objects.exists())


class AdminSecurityTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin')
        self.admin.user_permissions.add(*Permission.objects.filter(codename__in=['access_admin', 'manage_theory']))
        self.client.force_login(self.admin)

    def test_dashboard_hides_exam_results_without_permission(self):
        response = self.client.get(reverse('admin_index'))
        self.assertEqual(list(response.context['recent_results']), [])
        self.assertNotContains(response, 'Neueste Prüfungsabgaben')

    def test_import_rejects_oversized_file(self):
        level = Levels.objects.create(name='S', slug='s', order=1)
        catalog = Questions_Catalogs.objects.create(title='K', short_title='K', level=level)
        big = SimpleUploadedFile('fragen.json', b'[' + b' ' * (5 * 1024 * 1024 + 10) + b']', content_type='application/json')
        response = self.client.post(reverse('admin_import_questions'), {'catalog': catalog.pk, 'file': big})
        self.assertContains(response, 'zu groß')
        self.assertFalse(Questions_Theory.objects.exists())


class HealthTests(TestCase):
    def test_health_ok_without_login(self):
        response = self.client.get(reverse('health'))
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_security_headers(self):
        response = self.client.get(reverse('login'))
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
