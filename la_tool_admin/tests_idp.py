"""Divera-Login über die feste Divera-ID, Prüfung auf aktive Mitglieder und IdP-Gruppenabgleich mit Festsetzung."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.contrib.sessions.backends.db import SessionStore
from django.urls import reverse

from app import login_function as lf
from app.login_function import DiveraError
from .models import AutoGroupRule, PinnedGroup, Profile
from .tests import grant
from .utils import sync_idp_groups


def member(ucr=111, quals=(), first='Max', last='Muster'):
    return {'ucr': ucr, 'firstname': first, 'lastname': last, 'qualifications': list(quals), 'groups': []}


class DiveraLoginTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().post('/login/')
        self.request.session = SessionStore()

    def login(self, username='max@example.org', password='pw', member_data=None, error=None):
        with patch.object(lf, 'divera_authenticate', return_value='token') as auth_mock, \
                patch.object(lf, 'divera_member_data', return_value=member_data or member()):
            if error:
                auth_mock.side_effect = error
            return lf.login(username, password, self.request)

    def test_new_divera_user_is_linked_by_ucr(self):
        user = self.login('Max@Example.org')
        self.assertEqual(user.username, 'max@example.org')
        self.assertEqual(user.profile.divera_ucr, 111)
        # Anderer Login-Name, gleiche Divera-ID → dasselbe Konto
        same = self.login('max.muster', member_data=member())
        self.assertEqual(same.pk, user.pk)

    def test_existing_local_account_is_not_taken_over(self):
        local = User.objects.create_user('chef@example.org', password='geheim')
        self.assertIsNone(self.login('chef@example.org', 'divera-pw', member_data=member(ucr=222)))
        local.refresh_from_db()
        self.assertTrue(local.check_password('geheim'))
        self.assertIn('anderes Konto', self.request.session['login_error'])

    def test_divera_account_always_checked_against_divera(self):
        user = self.login()
        # Passwort lokal noch gültig, Divera lehnt aber ab (Passwort geändert / Konto entfernt)
        result = self.login(error=DiveraError('rejected', 'Ungültige Divera-Zugangsdaten.'))
        self.assertIsNone(result)
        # Divera nicht erreichbar → lokal gespeichertes Passwort als Notfall
        result = self.login(error=DiveraError('unreachable', 'Divera ist aktuell nicht erreichbar.'))
        self.assertEqual(result.pk, user.pk)

    def test_left_member_is_deactivated_and_reactivated_on_return(self):
        user = self.login()
        with patch.object(lf, 'divera_authenticate', return_value='token'), \
                patch.object(lf, 'divera_member_data', side_effect=DiveraError('not_member', 'weg')):
            self.assertIsNone(lf.login('max@example.org', 'pw', self.request))
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertIsNotNone(user.profile.divera_left_at)
        # Wieder im Standort → Konto wieder aktiv
        self.assertTrue(self.login().is_active)

    def test_admin_locked_account_stays_locked(self):
        user = self.login()
        User.objects.filter(pk=user.pk).update(is_active=False)
        self.assertIsNone(self.login())


class IdpGroupSyncTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jugend')
        self.profile = Profile.objects.create(user=self.user, login_source=Profile.SOURCE_DIVERA,
                                              divera_qualifications=[1])
        self.divera_group = Group.objects.create(name='Bronze-Prüflinge')
        AutoGroupRule.objects.create(group=self.divera_group, divera_qual_ids=[1])
        self.entra_group = Group.objects.create(name='Betreuer')
        AutoGroupRule.objects.create(group=self.entra_group, entra_group_ids=['abc'])

    def test_divera_rule_adds_and_removes(self):
        sync_idp_groups(self.user)
        self.assertTrue(self.user.groups.filter(pk=self.divera_group.pk).exists())
        Profile.objects.filter(pk=self.profile.pk).update(divera_qualifications=[])
        sync_idp_groups(self.user)
        self.assertFalse(self.user.groups.filter(pk=self.divera_group.pk).exists())

    def test_unknown_source_does_not_remove(self):
        # Nie per Entra angemeldet: Entra-Regel kann nicht entscheiden → manuelle Mitgliedschaft bleibt
        self.user.groups.add(self.entra_group)
        sync_idp_groups(self.user)
        self.assertTrue(self.user.groups.filter(pk=self.entra_group.pk).exists())

    def test_pinned_membership_survives(self):
        Profile.objects.filter(pk=self.profile.pk).update(divera_qualifications=[], entra_group_ids=[])
        PinnedGroup.objects.create(user=self.user, group=self.divera_group)
        self.user.groups.add(self.divera_group, self.entra_group)
        sync_idp_groups(self.user)
        groups = set(self.user.groups.values_list('pk', flat=True))
        self.assertIn(self.divera_group.pk, groups)
        self.assertNotIn(self.entra_group.pk, groups)

    @override_settings(AZURE_GROUPS_MAPPING={'admins-oid': 'LA-Tool-Admins'})
    def test_entra_mapping_respects_pins(self):
        admins = Group.objects.create(name='LA-Tool-Admins')
        self.user.groups.add(admins)
        Profile.objects.filter(pk=self.profile.pk).update(entra_group_ids=['other'])
        sync_idp_groups(self.user)
        self.assertFalse(self.user.groups.filter(pk=admins.pk).exists())
        PinnedGroup.objects.create(user=self.user, group=admins)
        self.user.groups.add(admins)
        sync_idp_groups(self.user)
        self.assertTrue(self.user.groups.filter(pk=admins.pk).exists())


class PinGroupAdminTests(TestCase):
    def setUp(self):
        self.target = User.objects.create_user('jugend')
        self.group = Group.objects.create(name='Betreuer')
        self.admin = User.objects.create_user('admin')
        grant(self.admin, 'access_admin', 'manage_users')

    def post(self, action):
        return self.client.post(reverse('admin_users'), {'user_id': self.target.pk, 'action': action,
                                                         'group_id': self.group.pk})

    def test_pinning_requires_manage_groups(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.post('add_group').status_code, 403)

    def test_add_pin_unpin_remove(self):
        grant(self.admin, 'manage_groups')
        self.client.force_login(self.admin)
        self.post('add_group')
        self.assertTrue(PinnedGroup.objects.filter(user=self.target, group=self.group).exists())
        self.post('unpin_group')
        self.assertFalse(PinnedGroup.objects.exists())
        self.assertTrue(self.target.groups.filter(pk=self.group.pk).exists())
        self.post('remove_group')
        self.assertFalse(self.target.groups.filter(pk=self.group.pk).exists())


class SyncDiveraUsersTests(TestCase):
    def setUp(self):
        self.stay = User.objects.create_user('bleibt')
        Profile.objects.create(user=self.stay, login_source=Profile.SOURCE_DIVERA, divera_ucr=1)
        self.gone = User.objects.create_user('weg')
        Profile.objects.create(user=self.gone, login_source=Profile.SOURCE_DIVERA, divera_ucr=2,
                               divera_api_key='token-weg')
        self.admin_only = User.objects.create_user('verwaltung')
        Profile.objects.create(user=self.admin_only, login_source=Profile.SOURCE_DIVERA, divera_ucr=3,
                               divera_api_key='token-verwaltung')

    def own_token_check(self, token):
        # Nicht in der Personenliste: „weg“ ist ausgetreten, „verwaltung“ ist Mitglied ohne Alarmierung
        if token == 'token-weg':
            raise DiveraError('not_member', 'weg')
        return member(ucr=3, quals=[7])

    def run_sync(self, consumers):
        pulls = [
            {'success': True, 'data': {'ucr': {'9': {'cluster_id': 20369}}}},
            {'success': True, 'data': {'cluster': {'consumer': consumers}}},
        ]
        with override_settings(), patch('la_tool.env.DIVERA_ADMIN_USER_API_KEY', 'key'), \
                patch('la_tool.env.DIVERA_Site_ID', '20369'), \
                patch('app.management.commands.sync_divera_users._divera_pull', side_effect=pulls),                 patch('app.management.commands.sync_divera_users.divera_member_data', side_effect=self.own_token_check):
            call_command('sync_divera_users', stdout=StringIO(), stderr=StringIO())

    def test_missing_members_are_deactivated(self):
        self.run_sync({'1': {'qualifications': [5]}, '9': {}})
        self.stay.refresh_from_db()
        self.gone.refresh_from_db()
        self.assertTrue(self.stay.is_active)
        self.assertEqual(self.stay.profile.divera_qualifications, [5])
        self.assertFalse(self.gone.is_active)
        self.admin_only.refresh_from_db()
        self.assertTrue(self.admin_only.is_active)
        self.assertEqual(self.admin_only.profile.divera_qualifications, [7])

    def test_empty_member_list_changes_nothing(self):
        self.run_sync({})
        self.gone.refresh_from_db()
        self.assertTrue(self.gone.is_active)
