import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException

from app.models import Levels, Questions_Catalogs, Questions_Practical, Work
from la_tool_admin.models import PushSubscription, UserNotification
from la_tool_admin.push import send_push


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='app', codename__in=codenames))


class AdminPermissionTests(TestCase):
    """Zugriffsregeln des Admin-Bereichs: Login, 'access_admin' und Einzelrechte."""

    def setUp(self):
        self.member = User.objects.create_user('member', password='pw')
        self.viewer = User.objects.create_user('viewer', password='pw')
        grant(self.viewer, 'access_admin')
        self.user_manager = User.objects.create_user('usermanager', password='pw')
        grant(self.user_manager, 'access_admin', 'manage_users')
        self.other_admin = User.objects.create_user('otheradmin', password='pw')
        grant(self.other_admin, 'access_admin')

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['first_run_done'] = True
        session.save()

    def test_anonymous_is_sent_to_login_with_next(self):
        for name in ('admin_index', 'admin_catalog_create', 'admin_users'):
            url = reverse(name)
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_member_without_admin_access_gets_403_page(self):
        self.login(self.member)
        response = self.client.get(reverse('admin_index'))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, 'Admin-Bereich zugreifen', status_code=403)

    def test_viewer_sees_overview_but_not_protected_pages(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse('admin_index')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_catalog')).status_code, 200)
        for name in ('admin_catalog_create', 'admin_users', 'admin_settings', 'admin_exam_create'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_viewer_does_not_see_links_to_protected_pages(self):
        self.login(self.viewer)
        html = self.client.get(reverse('admin_catalog')).content.decode()
        self.assertNotIn(reverse('admin_catalog_create'), html)
        self.assertNotIn(reverse('admin_users'), html)
        self.assertNotIn(reverse('admin_settings'), html)

    def test_user_manager_cannot_grant_permissions(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {
            'user_id': self.member.pk, 'action': 'toggle_perm', 'perm_codename': 'manage_users',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.get(pk=self.member.pk).has_perm('app.manage_users'))

    def test_user_manager_cannot_reset_admin_password(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {'user_id': self.other_admin.pk, 'action': 'reset_password'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.get(pk=self.other_admin.pk).check_password('pw'))

    def test_user_manager_can_reset_member_password(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {'user_id': self.member.pk, 'action': 'reset_password'})
        self.assertRedirects(response, reverse('admin_users'), fetch_redirect_response=False)
        self.assertFalse(User.objects.get(pk=self.member.pk).check_password('pw'))


class AppAccessTests(TestCase):
    """Sichtbarkeit von Diensten und Aufgaben sowie Login-Rücksprung."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        catalog = Questions_Catalogs.objects.create(title='Katalog', short_title='K', level=level)
        self.task = Questions_Practical.objects.create(question='Knoten', catalog=catalog)
        self.draft_task = Questions_Practical.objects.create(question='Entwurf', catalog=catalog, is_draft=True)
        start = timezone.now() + timedelta(days=1)
        self.work = Work.objects.create(title='Dienst', date=start)
        self.draft_work = Work.objects.create(title='Entwurf', date=start, is_draft=True)
        self.group_work = Work.objects.create(title='Fremde Gruppe', date=start)
        self.group_work.groups.add(Group.objects.create(name='Andere'))

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['first_run_done'] = True
        session.save()

    def test_work_detail_hides_drafts_and_other_groups(self):
        self.login()
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.work.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.draft_work.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.group_work.pk])).status_code, 404)

    def test_practical_detail_hides_drafts(self):
        self.assertEqual(self.client.get(reverse('practical_detail', args=[self.task.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('practical_detail', args=[self.draft_task.pk])).status_code, 404)

    def test_login_redirects_back_to_requested_page(self):
        url = reverse('work')
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_login_ignores_foreign_next(self):
        self.login()
        response = self.client.get(reverse('login') + '?next=https://evil.example/')
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)


class DraftLevelTests(TestCase):
    """Stufen im Entwurf dürfen für Nutzer weder sichtbar noch wählbar sein."""

    def setUp(self):
        self.live = Levels.objects.create(name='Teststufe', slug='teststufe', order=900)
        self.draft = Levels.objects.create(name='Entwurfsstufe', slug='entwurfsstufe', order=901, is_draft=True)

    def test_draft_level_not_in_level_switcher(self):
        html = self.client.get(reverse('home')).content.decode()
        self.assertIn('Teststufe', html)
        self.assertNotIn('Entwurfsstufe', html)

    def test_draft_level_cannot_be_selected(self):
        self.client.get(reverse('set_la_filter', args=[self.draft.slug]))
        self.assertNotEqual(self.client.session.get('la_filter'), self.draft.slug)

    def test_draft_level_in_session_is_replaced(self):
        session = self.client.session
        session['la_filter'] = self.draft.slug
        session.save()
        self.client.get(reverse('home'))
        self.assertNotEqual(self.client.session.get('la_filter'), self.draft.slug)

    def test_next_level_skips_drafts(self):
        after = Levels.objects.create(name='Danach', slug='danach', order=902)
        self.assertEqual(self.live.next_level, after)


@override_settings(VAPID_PUBLIC_KEY='pub', VAPID_PRIVATE_KEY='priv', VAPID_SUBJECT='mailto:test@example.org')
class PushTests(TestCase):
    """Web Push: Abos verwalten, Versand, Admin-Nachricht. webpush() ist gemockt."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        self.other = User.objects.create_user('andere', password='pw')
        self.group = Group.objects.create(name='Jugendliche')
        self.user.groups.add(self.group)
        self.sender = User.objects.create_user('betreuer', password='pw')
        grant(self.sender, 'access_admin', 'send_notifications')

    def subscribe(self, user, endpoint):
        return PushSubscription.objects.create(user=user, endpoint=endpoint, p256dh='k', auth='a')

    def login(self, user):
        self.client.force_login(user)

    def test_subscribe_requires_login(self):
        response = self.client.post(reverse('push_subscribe'), '{}', content_type='application/json')
        self.assertEqual(response.status_code, 401)

    def test_subscribe_stores_and_unsubscribe_removes(self):
        self.login(self.user)
        body = {'endpoint': 'https://fcm.googleapis.com/fcm/send/abc', 'keys': {'p256dh': 'key', 'auth': 'secret'}}
        response = self.client.post(reverse('push_subscribe'), json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PushSubscription.objects.filter(user=self.user, endpoint=body['endpoint']).exists())
        self.client.post(reverse('push_unsubscribe'), json.dumps({'endpoint': body['endpoint']}), content_type='application/json')
        self.assertFalse(PushSubscription.objects.exists())

    def test_subscribe_rejects_invalid_data(self):
        self.login(self.user)
        response = self.client.post(reverse('push_subscribe'), json.dumps({'endpoint': 'http://x'}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    @patch('la_tool_admin.push.webpush')
    def test_send_push_removes_expired_subscriptions(self, webpush):
        self.subscribe(self.user, 'https://fcm.googleapis.com/fcm/send/ok')
        gone = self.subscribe(self.user, 'https://fcm.googleapis.com/fcm/send/gone')

        def fake(subscription_info, **kwargs):
            if subscription_info['endpoint'] == gone.endpoint:
                raise WebPushException('gone', response=SimpleNamespace(status_code=410))
        webpush.side_effect = fake

        self.assertEqual(send_push([self.user], 'Titel', 'Text', '/'), 1)
        self.assertFalse(PushSubscription.objects.filter(pk=gone.pk).exists())
        payload = json.loads(webpush.call_args_list[0].kwargs['data'])
        # Antippen führt über die gespeicherte Benachrichtigung (markiert sie als gelesen)
        notification = UserNotification.objects.get(user=self.user)
        self.assertEqual(payload, {'title': 'Titel', 'body': 'Text', 'url': f'/benachrichtigungen/{notification.pk}/',
                                   'unread': 1, 'actions': []})

    @override_settings(VAPID_PRIVATE_KEY='')
    @patch('la_tool_admin.push.webpush')
    def test_send_push_without_keys_sends_nothing(self, webpush):
        self.subscribe(self.user, 'https://fcm.googleapis.com/fcm/send/ok')
        self.assertEqual(send_push([self.user], 'T', 'B'), 0)
        webpush.assert_not_called()

    def test_admin_message_requires_permission(self):
        viewer = User.objects.create_user('viewer', password='pw')
        grant(viewer, 'access_admin')
        self.login(viewer)
        self.assertEqual(self.client.get(reverse('admin_push_message')).status_code, 403)

    @patch('la_tool_admin.push.webpush')
    def test_admin_message_to_group_reaches_only_members(self, webpush):
        self.subscribe(self.user, 'https://fcm.googleapis.com/fcm/send/member')
        self.subscribe(self.other, 'https://fcm.googleapis.com/fcm/send/other')
        self.login(self.sender)
        response = self.client.post(reverse('admin_push_message'), {
            'title': 'Dienst fällt aus', 'body': 'Heute kein Dienst.', 'target': 'work', 'groups': [self.group.pk],
        }, follow=True)
        self.assertContains(response, 'Push-Benachrichtigung an 1 Gerät gesendet')
        endpoints = [c.kwargs['subscription_info']['endpoint'] for c in webpush.call_args_list]
        self.assertEqual(endpoints, ['https://fcm.googleapis.com/fcm/send/member'])

    @patch('la_tool_admin.push.webpush')
    def test_admin_push_test_reaches_only_own_devices(self, webpush):
        self.subscribe(self.sender, 'https://fcm.googleapis.com/fcm/send/admin')
        self.subscribe(self.user, 'https://fcm.googleapis.com/fcm/send/member')
        self.login(self.sender)
        response = self.client.post(reverse('admin_push_test'), follow=True)
        self.assertContains(response, 'Push-Benachrichtigung an 1 Gerät gesendet')
        endpoints = [c.kwargs['subscription_info']['endpoint'] for c in webpush.call_args_list]
        self.assertEqual(endpoints, ['https://fcm.googleapis.com/fcm/send/admin'])

    @patch('la_tool_admin.push.webpush')
    def test_admin_push_test_without_own_subscription(self, webpush):
        self.login(self.sender)
        response = self.client.post(reverse('admin_push_test'), follow=True)
        self.assertContains(response, 'auf keinem Gerät Push aktiviert')
        webpush.assert_not_called()

    @patch('la_tool_admin.push.webpush')
    def test_admin_push_test_reports_failure(self, webpush):
        self.subscribe(self.sender, 'https://fcm.googleapis.com/fcm/send/admin')
        webpush.side_effect = WebPushException('fehler', response=SimpleNamespace(status_code=500))
        self.login(self.sender)
        response = self.client.post(reverse('admin_push_test'), follow=True)
        self.assertContains(response, 'Test fehlgeschlagen')
        self.assertTrue(PushSubscription.objects.filter(user=self.sender).exists())

    def test_admin_push_test_requires_permission(self):
        viewer = User.objects.create_user('viewer', password='pw')
        grant(viewer, 'access_admin')
        self.login(viewer)
        self.assertEqual(self.client.post(reverse('admin_push_test')).status_code, 403)
