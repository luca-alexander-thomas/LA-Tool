"""PWA: Benachrichtigungen (Posteingang, Zähler), Offline-Abgabe von Trainings, Offline-Nachschlagen, Service Worker."""
import json

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from la_tool_admin.models import UserNotification
from la_tool_admin.push import send_push

from .models import Levels, Questions_Catalogs, Questions_Theory, TrainingResultData


class PwaBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('jugend')
        self.client.force_login(self.user)
        self.level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        self.catalog = Questions_Catalogs.objects.create(title='Alpha', short_title='A', level=self.level)
        self.q = [Questions_Theory.objects.create(question=f'F{i}', number=str(i), catalog=self.catalog,
                                                  answer_text='Ja', answer_choice=['Ja', 'Nein']) for i in range(3)]
        session = self.client.session
        session['la_filter'] = 'teststufe'
        session.save()


class NotificationTests(PwaBase):
    def test_send_push_stores_notification_without_devices(self):
        self.assertEqual(send_push([self.user], 'Neue Prüfung', 'Text', '/pruefungen/'), 0)
        notification = UserNotification.objects.get()
        self.assertEqual((notification.title, notification.url, notification.read_at), ('Neue Prüfung', '/pruefungen/', None))
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['unread_notifications'], 1)
        self.assertContains(response, 'data-unread="1"')

    def test_external_url_is_not_stored(self):
        send_push([self.user], 'X', '', '//evil.example/')
        self.assertEqual(UserNotification.objects.get().url, '/')

    def test_open_marks_read_and_redirects(self):
        send_push([self.user], 'A', '', '/pruefungen/')
        notification = UserNotification.objects.get()
        response = self.client.get(reverse('notification_open', args=[notification.pk]))
        self.assertRedirects(response, '/pruefungen/', fetch_redirect_response=False)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_list_marks_all_read_and_is_private(self):
        other = User.objects.create_user('andere')
        send_push([self.user, other], 'A', '', '/')
        response = self.client.get(reverse('notification_list'))
        self.assertEqual(len(response.context['notifications']), 1)
        self.assertFalse(UserNotification.objects.filter(user=self.user, read_at__isnull=True).exists())
        self.assertTrue(UserNotification.objects.filter(user=other, read_at__isnull=True).exists())
        foreign = UserNotification.objects.get(user=other)
        self.assertEqual(self.client.get(reverse('notification_open', args=[foreign.pk])).status_code, 404)


class OfflineTrainingTests(PwaBase):
    def answers(self):
        return json.dumps({str(q.pk): ['a'] for q in self.q})

    def test_late_submit_with_other_run_active(self):
        self.client.post(reverse('training_today'))  # neuer Durchgang läuft
        response = self.client.post(reverse('training_run'), {
            'run_id': 'offline123', 'question_ids': json.dumps([q.pk for q in self.q]), 'answers': self.answers()})
        result = TrainingResultData.objects.get()
        self.assertRedirects(response, reverse('training_result', args=[result.pk]))
        self.assertEqual(result.questions, [q.pk for q in self.q])
        # erneut gesendet (z.B. zweimal online): kein zweites Ergebnis
        again = self.client.post(reverse('training_run'), {
            'run_id': 'offline123', 'question_ids': json.dumps([q.pk for q in self.q]), 'answers': self.answers()})
        self.assertRedirects(again, reverse('training_result', args=[result.pk]))
        self.assertEqual(TrainingResultData.objects.count(), 1)

    def test_late_submit_ignores_draft_questions(self):
        self.q[0].is_draft = True
        self.q[0].save()
        self.client.post(reverse('training_run'), {
            'run_id': 'x', 'question_ids': json.dumps([q.pk for q in self.q] + ['boese']), 'answers': self.answers()})
        self.assertEqual(TrainingResultData.objects.get().questions, [self.q[1].pk, self.q[2].pk])

    def test_today_by_get_for_shortcut(self):
        response = self.client.get(reverse('training_today'))
        self.assertRedirects(response, reverse('training_run'))

    def test_due_count_in_tabbar(self):
        TrainingResultData.objects.create(name='T', user=self.user, questions=[self.q[0].pk], answers={str(self.q[0].pk): ['b']})
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['due_count'], 1)
        self.assertContains(response, '1 Fragen fällig')


class OfflineLookupTests(PwaBase):
    def test_data_has_solutions_but_no_personal_data(self):
        TrainingResultData.objects.create(name='T', user=self.user, questions=[self.q[0].pk], answers={})
        data = self.client.get(reverse('theory_offline_data')).json()
        catalog = data['levels'][0]['catalogs'][0]
        self.assertEqual(catalog['questions'][0]['choices'], [['a', 'Ja', True], ['b', 'Nein', False]])
        self.assertNotIn('jugend', json.dumps(data))

    def test_data_needs_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('theory_offline_data')).status_code, 403)

    def test_service_worker_and_manifest(self):
        sw = self.client.get(reverse('service_worker')).content.decode()
        self.assertIn(reverse('theory_offline_page'), sw)
        manifest = self.client.get(reverse('manifest')).json()
        self.assertEqual(manifest['id'], '/')
        self.assertEqual(manifest['shortcuts'][0]['url'], reverse('training_today'))
        self.assertEqual(self.client.get(reverse('theory_offline_page')).status_code, 200)


class RememberMeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jugend', password='geheim')

    def post_login(self, **extra):
        from unittest import mock
        with mock.patch('app.views.login_func.login', return_value=self.user):
            return self.client.post(reverse('login'), {'username': 'jugend', 'password': 'geheim', **extra})

    def test_remember_sets_persistent_cookie(self):
        response = self.post_login(remember='1')
        cookie = response.cookies['sessionid']
        self.assertEqual(cookie['max-age'], 90 * 24 * 60 * 60)
        self.assertFalse(self.client.session.get_expire_at_browser_close())

    def test_without_remember_session_ends_with_browser(self):
        response = self.post_login()
        self.assertEqual(response.cookies['sessionid']['max-age'], '')
        self.assertTrue(self.client.session.get_expire_at_browser_close())

    def test_remembered_session_is_renewed_once_a_day(self):
        import time
        self.post_login(remember='1')
        session = self.client.session
        session['renewed_at'] = int(time.time()) - 2 * 24 * 60 * 60
        session.save()
        response = self.client.get(reverse('profile'))
        self.assertIn('sessionid', response.cookies)  # Cookie mit neuem Ablauf
        self.assertNotIn('sessionid', self.client.get(reverse('profile')).cookies)  # heute schon verlängert


class DiveraPromptTests(TestCase):
    """Ohne Divera-Verknüpfung: Wizard nur beim ersten Besuch, danach Kachel auf der Startseite."""

    def setUp(self):
        from la_tool_admin.models import Profile
        self.user = User.objects.create_user('ohne-divera', password='pw')
        Profile.objects.create(user=self.user, login_source='entra')
        self.client.force_login(self.user)

    def test_wizard_only_once_then_tile(self):
        first = self.client.get(reverse('home'))
        self.assertRedirects(first, reverse('first_run_wizard'))
        # neue Sitzung (erneuter Login): kein Wizard mehr, stattdessen Kachel
        self.client.logout()
        self.client.force_login(self.user)
        second = self.client.get(reverse('home'))
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, 'Divera verknüpfen')

    def test_linked_user_sees_no_tile(self):
        self.user.profile.divera_ucr = 123
        self.user.profile.save()
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Divera verknüpfen')
