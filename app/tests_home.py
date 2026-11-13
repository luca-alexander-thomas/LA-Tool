"""Startseite als einziges Dashboard (Issue #12), gemerkte Fragen (Issue #18) und Hinweisbanner."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from la_tool_admin.tests import grant
from .models import Levels, QuestionBookmark, Questions_Catalogs, Questions_Theory, SiteSettings
from .tests_learning import LearningBase


class HomeDashboardTests(LearningBase):
    def test_old_pages_redirect_to_home(self):
        self.assertRedirects(self.client.get(reverse('excercise')), reverse('home'))
        self.assertRedirects(self.client.get(reverse('learning_stats')), reverse('home') + '#lernstand',
                             fetch_redirect_response=False)

    def test_home_contains_learning_overview(self):
        self.train({self.qa[0]: True, self.qa[1]: False}, days_ago=1)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['progress']['total'], 6)
        self.assertEqual(len(response.context['rows']), 6)
        for text in ('Heute lernen', 'Tage in Folge geübt', 'Alle Fragen', 'Kataloge', 'Gemerkte Fragen', 'Letzte Trainings'):
            self.assertContains(response, text)
        # Keine Schnellzugriff-Kacheln mehr: die Navigation steht in Kopfzeile und Tab-Leiste
        self.assertNotContains(response, 'Schnellzugriff')

    def test_practice_menu_without_overview_and_stats(self):
        html = self.client.get(reverse('training_config')).content.decode()
        self.assertNotIn(reverse('learning_stats'), html)
        self.assertNotIn('href="%s"' % reverse('excercise'), html)

    def test_saved_questions_on_home(self):
        QuestionBookmark.objects.create(user=self.user, question=self.qb[1])
        response = self.client.get(reverse('home'))
        saved = response.context['saved_questions']
        self.assertEqual([s['question'] for s in saved], [self.qb[1]])
        self.assertEqual(saved[0]['choices'], [('a', 'Ja', True), ('b', 'Nein', False)])
        self.assertContains(response, 'id="gemerkt"')
        self.assertContains(response, 'Gemerkte Fragen üben')

        # Der Knopf startet eine Runde nur mit den gemerkten Fragen
        response = self.client.post(reverse('training_config'), {
            'mode': 'saved', 'count': '1', 'catalogs': [c.pk for c in response.context['catalogs']]})
        self.assertRedirects(response, reverse('training_run'), fetch_redirect_response=False)
        self.assertEqual(self.client.session['training_question_ids'], [self.qb[1].pk])

    def test_saved_questions_of_other_levels_are_counted(self):
        other_level = Levels.objects.create(name='Andere', slug='andere', order=100)
        catalog = Questions_Catalogs.objects.create(title='X', short_title='X', level=other_level)
        question = Questions_Theory.objects.create(question='X?', catalog=catalog, answer_text='Ja', answer_choice=['Ja'])
        QuestionBookmark.objects.create(user=self.user, question=question)
        response = self.client.get(reverse('home'))
        self.assertEqual(response.context['saved_questions'], [])
        self.assertEqual(response.context['other_level_saved'], 1)
        self.assertContains(response, 'Noch keine Fragen gemerkt')
        self.assertContains(response, '1 gemerkte Frage anderer Stufen')

    def test_home_without_theory_questions(self):
        Questions_Theory.objects.all().delete()
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Alle Fragen')
        self.assertContains(response, 'Nächster Dienst')


class SiteNoticeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('jugend')
        self.settings = SiteSettings.get()

    def set_notice(self, visibility, text='Dienst fällt aus', level='info'):
        SiteSettings.objects.filter(pk=self.settings.pk).update(
            notice_text=text, notice_visibility=visibility, notice_level=level)

    def test_visibility(self):
        cases = [
            (SiteSettings.NOTICE_OFF, False, False),
            (SiteSettings.NOTICE_PUBLIC, True, True),
            (SiteSettings.NOTICE_USERS, False, True),
        ]
        for visibility, anonymous_sees, user_sees in cases:
            self.set_notice(visibility)
            self.client.logout()
            self.assertEqual('Dienst fällt aus' in self.client.get(reverse('home')).content.decode(), anonymous_sees, visibility)
            self.client.force_login(self.user)
            self.assertEqual('Dienst fällt aus' in self.client.get(reverse('home')).content.decode(), user_sees, visibility)

    def test_text_is_escaped_and_keeps_line_breaks(self):
        self.set_notice(SiteSettings.NOTICE_PUBLIC, text='<b>Achtung</b>\nZweite Zeile', level='warning')
        response = self.client.get(reverse('home'))
        self.assertContains(response, '&lt;b&gt;Achtung&lt;/b&gt;<br>Zweite Zeile')
        self.assertContains(response, 'alert-warning')

    def test_only_on_home(self):
        self.set_notice(SiteSettings.NOTICE_PUBLIC)
        self.assertNotContains(self.client.get(reverse('training_config')), 'Dienst fällt aus')

    def test_admin_settings(self):
        admin = User.objects.create_user('admin')
        grant(admin, 'access_admin', 'manage_settings')
        self.client.force_login(admin)
        url = reverse('admin_settings')
        response = self.client.post(url, {'section': 'notice', 'notice_text': '', 'notice_level': 'info',
                                          'notice_visibility': SiteSettings.NOTICE_PUBLIC})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bitte einen Text eingeben')

        response = self.client.post(url, {'section': 'notice', 'notice_text': 'Termin', 'notice_level': 'warning',
                                          'notice_visibility': SiteSettings.NOTICE_USERS})
        self.assertRedirects(response, url)
        notice = SiteSettings.get()
        self.assertEqual((notice.notice_text, notice.notice_level, notice.notice_visibility),
                         ('Termin', 'warning', SiteSettings.NOTICE_USERS))
        self.assertEqual(notice.training_pass_threshold, 75)  # andere Einstellung unverändert

        # Bestehensgrenze speichern lässt das Banner unverändert
        self.client.post(url, {'training_pass_threshold': '80'})
        notice = SiteSettings.get()
        self.assertEqual((notice.training_pass_threshold, notice.notice_text), (80, 'Termin'))

    def test_admin_settings_requires_permission(self):
        other = User.objects.create_user('other')
        grant(other, 'access_admin')
        self.client.force_login(other)
        response = self.client.post(reverse('admin_settings'), {
            'section': 'notice', 'notice_text': 'X', 'notice_level': 'info', 'notice_visibility': 'public'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SiteSettings.get().notice_text, '')
