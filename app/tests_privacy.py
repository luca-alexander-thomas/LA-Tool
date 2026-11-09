"""Datenschutz und Konten: Divera-Key wird nicht gespeichert, Entra-Pflicht für Admins, PKCE-Login,
Datenexport, Lerndaten löschen, Löschkonzept, Rechtsseiten."""
import json
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from app import login_function as lf
from la_tool_admin.models import Profile, UserNotification

from .models import ExamResultData, QuestionBookmark, Questions_Catalogs, Questions_Theory, TrainingResultData, Levels


def member(ucr=7):
    return {'ucr': ucr, 'firstname': 'Max', 'lastname': 'Muster', 'qualifications': [30132], 'groups': []}


class DiveraKeyTests(TestCase):
    def test_divera_login_does_not_store_access_key(self):
        request = mock.Mock(session={})
        with mock.patch.object(lf, 'divera_authenticate', return_value='geheimer-key'), \
             mock.patch.object(lf, 'divera_member_data', return_value=member()), \
             mock.patch.object(lf, '_sync_groups'):
            user = lf.divera_login('max', 'pw', request)
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.divera_ucr, 7)
        self.assertFalse(any('geheimer-key' in str(v) for v in Profile.objects.filter(pk=profile.pk).values().first().values()))


class EntraOnlyAdminTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user('chef@thw-jugend-ge.de', password='pw')
        self.admin.user_permissions.add(Permission.objects.get(codename='access_admin'))
        Profile.objects.create(user=self.admin, login_source=Profile.SOURCE_ENTRA, entra_oid='oid', divera_ucr=7)

    def test_local_password_refused_for_entra_admin(self):
        request = mock.Mock(session={})
        with mock.patch.object(lf, 'divera_login', side_effect=AssertionError('nicht aufrufen')):
            self.assertIsNone(lf.login('chef@thw-jugend-ge.de', 'pw', request))
        self.assertEqual(request.session['login_error'], lf.ENTRA_ONLY_MESSAGE)

    def test_divera_password_refused_without_changing_account(self):
        request = mock.Mock(session={})
        with mock.patch.object(lf, 'divera_authenticate', return_value='key'), \
             mock.patch.object(lf, 'divera_member_data', return_value=member(ucr=7)):
            self.assertIsNone(lf.login('divera-name', 'divera-pw', request))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.profile.login_source, Profile.SOURCE_ENTRA)
        self.assertTrue(self.admin.check_password('pw'))  # kein neues Passwort gesetzt

    def test_admin_without_microsoft_and_normal_users_unaffected(self):
        local_admin = User.objects.create_superuser('admin', password='pw')
        self.assertEqual(lf.login('admin', 'pw', mock.Mock(session={})), local_admin)
        member_user = User.objects.create_user('jugend', password='pw')
        Profile.objects.create(user=member_user, entra_oid='oid-2')
        self.assertFalse(lf.entra_only(member_user))


@override_settings(MICROSOFT_AUTH_CLIENT_ID='cid', MICROSOFT_AUTH_TENANT_ID='tid', MICROSOFT_AUTH_CLIENT_SECRET='s',
                   MICROSOFT_AUTH_REDIRECT_URI='https://example.org/microsoft-callback/')
class EntraPkceTests(TestCase):
    def test_login_uses_auth_code_flow_with_small_scope(self):
        client = mock.Mock()
        client.initiate_auth_code_flow.return_value = {'state': 'st', 'auth_uri': 'https://login.microsoftonline.com/x'}
        with mock.patch('la_tool_admin.views.msal.ConfidentialClientApplication', return_value=client):
            response = self.client.get(reverse('microsoft_login'))
        self.assertEqual(response['Location'], 'https://login.microsoftonline.com/x')
        self.assertEqual(client.initiate_auth_code_flow.call_args.args[0], ['User.Read'])
        self.assertEqual(self.client.session['entra_flow']['state'], 'st')

    def test_callback_rejects_wrong_state(self):
        session = self.client.session
        session['entra_flow'] = {'state': 'st'}
        session.save()
        response = self.client.get(reverse('microsoft_callback'), {'state': 'falsch', 'code': 'c'})
        self.assertContains(response, 'State stimmt nicht überein')


class MyDataTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jugend', first_name='Jule')
        self.client.force_login(self.user)
        level = Levels.objects.create(name='S', slug='s-priv', order=950)
        catalog = Questions_Catalogs.objects.create(title='K', short_title='K', level=level)
        self.q = Questions_Theory.objects.create(question='F', catalog=catalog, answer_text='Ja', answer_choice=['Ja', 'Nein'])
        TrainingResultData.objects.create(name='T', user=self.user, questions=[self.q.pk], answers={})
        ExamResultData.objects.create(name='P', user=self.user, questions=[], answers={}, meta_reference={'score': 1}, state='hidden')
        QuestionBookmark.objects.create(user=self.user, question=self.q)

    def test_export_contains_own_data_but_hides_unreleased_scores(self):
        response = self.client.get(reverse('my_data_export'))
        self.assertIn('attachment', response['Content-Disposition'])
        data = json.loads(response.content)
        self.assertEqual(data['konto']['vorname'], 'Jule')
        self.assertEqual(len(data['trainings']), 1)
        self.assertIsNone(data['pruefungen'][0]['ergebnis'])
        self.assertEqual(data['gemerkte_fragen'], [self.q.pk])

    def test_delete_learning_data_needs_confirmation_and_keeps_exams(self):
        self.client.post(reverse('my_learning_data_delete'), {'confirm': 'ja'})
        self.assertTrue(TrainingResultData.objects.exists())
        self.client.post(reverse('my_learning_data_delete'), {'confirm': 'LÖSCHEN'})
        self.assertFalse(TrainingResultData.objects.exists())
        self.assertFalse(QuestionBookmark.objects.exists())
        self.assertTrue(ExamResultData.objects.exists())


class CleanupTests(TestCase):
    def test_deletes_only_expired_data(self):
        user = User.objects.create_user('aktiv')
        old = TrainingResultData.objects.create(name='alt', user=user, questions=[], answers={})
        TrainingResultData.objects.filter(pk=old.pk).update(meta_time=timezone.now() - timedelta(days=800))
        TrainingResultData.objects.create(name='neu', user=user, questions=[], answers={})
        gone = User.objects.create_user('weg', is_active=False)
        Profile.objects.create(user=gone, divera_left_at=timezone.now() - timedelta(days=400))
        locked = User.objects.create_user('gesperrt', is_active=False)  # von Admin gesperrt: bleibt
        Profile.objects.create(user=locked)
        UserNotification.objects.create(user=user, title='x')

        call_command('cleanup_data', '--dry-run', stdout=StringIO())
        self.assertEqual(TrainingResultData.objects.count(), 2)
        call_command('cleanup_data', stdout=StringIO())
        self.assertEqual(list(TrainingResultData.objects.values_list('name', flat=True)), ['neu'])
        self.assertFalse(User.objects.filter(username='weg').exists())
        self.assertTrue(User.objects.filter(username='gesperrt').exists())
        self.assertTrue(UserNotification.objects.exists())


class LegalPagesTests(TestCase):
    def test_pages_and_robots(self):
        for name in ('legal_privacy', 'legal_terms', 'legal_imprint'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertEqual(self.client.get('/robots.txt').content, b'User-agent: *\nDisallow: /\n')
        login = self.client.get(reverse('login'))
        self.assertContains(login, reverse('legal_privacy'))
        self.assertContains(login, 'noindex')
