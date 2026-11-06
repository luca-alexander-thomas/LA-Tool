from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import Permission, User
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from la_tool_admin.models import Profile

from .context_processors import la_filter
from .models import (
    Exams,
    Levels,
    Questions_Catalogs,
    Questions_Theory,
    SiteSettings,
    Work,
)
from .views import _save_exam_result, _score_question


def create_levels():
    bronze = Levels.objects.create(name='LA Bronze', slug='bronze', order=1)
    silber = Levels.objects.create(name='LA Silber', slug='silber', order=2)
    gold = Levels.objects.create(name='LA Gold', slug='gold', order=3)
    return bronze, silber, gold


def create_user(username='helfer', password='geheim-123', **extra):
    """Normaler Nutzer mit Divera-Profil, damit der First-Run-Wizard nicht greift."""
    user = User.objects.create_user(username=username, password=password, **extra)
    Profile.objects.create(user=user, divera_api_key='test-key')
    return user


class PwaTests(TestCase):
    def test_manifest(self):
        response = self.client.get(reverse('manifest'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/manifest+json')
        data = response.json()
        self.assertEqual(data['short_name'], 'LA-Tool')
        self.assertEqual(data['start_url'], reverse('home'))
        self.assertTrue(data['icons'])

    def test_service_worker(self):
        response = self.client.get(reverse('service_worker'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response['Content-Type'].startswith('application/javascript'))
        self.assertIn('no-cache', response['Cache-Control'])
        self.assertIn(reverse('offline'), response.content.decode())

    def test_offline_page(self):
        response = self.client.get(reverse('offline'))
        self.assertEqual(response.status_code, 200)


class AnonymousAccessTests(TestCase):
    def test_home_is_public(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_login_page_renders(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)

    def test_protected_pages_redirect_to_login(self):
        urls = [
            reverse('profile'),
            reverse('first_run_wizard'),
            reverse('exam_list'),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)


class LoginTests(TestCase):
    def setUp(self):
        create_levels()
        self.user = User.objects.create_user(username='helfer', password='geheim-123')

    def test_local_login_succeeds(self):
        response = self.client.post(reverse('login'), {'username': 'helfer', 'password': 'geheim-123'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)
        # Ohne Profil wird die erste Stufe als Filter gesetzt
        self.assertEqual(self.client.session['la_filter'], 'bronze')

    @mock.patch('app.login_function.requests.post')
    def test_wrong_password_shows_error(self, mock_post):
        # Lokale Anmeldung schlägt fehl -> Fallback auf Divera, der hier ebenfalls scheitert
        mock_post.return_value = mock.Mock(status_code=401)
        response = self.client.post(reverse('login'), {'username': 'helfer', 'password': 'falsch'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Divera-Login fehlgeschlagen.')
        self.assertNotIn('_auth_user_id', self.client.session)
        mock_post.assert_called_once()

    def test_logged_in_user_is_redirected_from_login(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('login'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_logout(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('logout'))
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)


class FirstRunWizardTests(TestCase):
    def test_user_without_divera_is_sent_to_wizard(self):
        user = User.objects.create_user(username='neu', password='geheim-123')
        Profile.objects.create(user=user)
        self.client.force_login(user)
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('first_run_wizard'), fetch_redirect_response=False)

    def test_skip_wizard(self):
        user = User.objects.create_user(username='neu', password='geheim-123')
        Profile.objects.create(user=user)
        self.client.force_login(user)
        response = self.client.post(reverse('first_run_wizard'), {'action': 'skip'})
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('home')).status_code, 200)


class AuthenticatedPagesTests(TestCase):
    def setUp(self):
        bronze, _, _ = create_levels()
        self.user = create_user()
        self.client.force_login(self.user)

        catalog = Questions_Catalogs.objects.create(title='Bronze-Katalog', short_title='B', level=bronze)
        self.question = Questions_Theory.objects.create(
            number='1', question='Wofür steht THW?', catalog=catalog,
            answer_text='Technisches Hilfswerk',
            answer_correct=['Technisches Hilfswerk'],
            answer_choice=['Technisches Hilfswerk', 'Technischer Hilfsweg', 'Tolles Helfer-Werk'],
        )
        self.work = Work.objects.create(
            title='Dienst', date=timezone.now() + timedelta(days=3), level=bronze,
        )
        self.exam = Exams.objects.create(
            name='Prüfung Bronze', level=bronze, catalog=catalog, time_in_min=30, visible=True,
        )
        self.exam.assigned_users.add(self.user)
        self.exam.questions.add(self.question)

    def test_pages_render(self):
        urls = [
            reverse('home'),
            reverse('profile'),
            reverse('first_run_wizard'),
            reverse('exam_list'),
            reverse('excercise'),
            reverse('training_config'),
            reverse('practical_list'),
            reverse('group_list'),
            reverse('work'),
            reverse('work_detail', args=[self.work.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_assigned_exam_is_listed(self):
        response = self.client.get(reverse('exam_list'))
        self.assertContains(response, 'Prüfung Bronze')

    def test_unassigned_exam_is_not_listed(self):
        Exams.objects.create(name='Geheime Prüfung', time_in_min=30, visible=True)
        response = self.client.get(reverse('exam_list'))
        self.assertNotContains(response, 'Geheime Prüfung')

    def test_set_la_filter(self):
        response = self.client.get(reverse('set_la_filter', args=['silber']))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.session['la_filter'], 'silber')


class ScoringTests(TestCase):
    def setUp(self):
        self.catalog = Questions_Catalogs.objects.create(title='Katalog', short_title='K')
        self.question = Questions_Theory.objects.create(
            question='Welche sind richtig?', catalog=self.catalog, answer_text='',
            answer_correct=['A', 'B'],
            answer_choice=['A', 'B', 'C', 'D'],
        )

    def test_all_or_nothing(self):
        self.assertEqual(_score_question(self.question, ['a', 'b']), 1)
        self.assertEqual(_score_question(self.question, ['a']), 0)
        self.assertEqual(_score_question(self.question, ['a', 'b', 'c']), 0)
        self.assertEqual(_score_question(self.question, ''), 0)

    def test_partial(self):
        self.catalog.multi_answer_scoring = Questions_Catalogs.SCORING_PARTIAL
        self.catalog.save()
        self.question.refresh_from_db()
        self.assertEqual(_score_question(self.question, ['a', 'b']), 1)
        self.assertEqual(_score_question(self.question, ['a']), 0.5)
        self.assertEqual(_score_question(self.question, ['a', 'c']), 0)
        self.assertEqual(_score_question(self.question, ['c', 'd']), 0)

    def test_single_answer_as_string(self):
        q = Questions_Theory.objects.create(
            question='Eine Antwort', catalog=self.catalog, answer_text='C',
            answer_choice=['A', 'B', 'C'],
        )
        self.assertEqual(_score_question(q, 'c'), 1)
        self.assertEqual(_score_question(q, 'a'), 0)

    def test_invalid_letters_are_ignored(self):
        self.assertEqual(_score_question(self.question, ['z', 'ab', '']), 0)

    def test_question_without_choices_scores_zero(self):
        q = Questions_Theory.objects.create(question='Ohne Auswahl', answer_text='x')
        self.assertEqual(_score_question(q, 'a'), 0)

    def test_save_exam_result(self):
        user = User.objects.create_user(username='pruefling')
        exam = Exams.objects.create(name='Prüfung', time_in_min=10, pass_threshold=1)
        result = _save_exam_result(user, exam, [self.question.pk], {str(self.question.pk): ['a', 'b']})
        self.assertEqual(result.meta_reference['score'], 1)
        self.assertEqual(result.meta_reference['total'], 1)
        self.assertTrue(result.meta_reference['passed'])
        self.assertEqual(result.state, 'hidden')


class ModelTests(TestCase):
    def test_question_correct_answers(self):
        q = Questions_Theory(question='?', answer_text='Text', answer_correct=None)
        self.assertEqual(q.correct_answers, ['Text'])
        self.assertFalse(q.is_multi_answer)
        q.answer_correct = ['A', 'B']
        self.assertEqual(q.correct_answers, ['A', 'B'])
        self.assertTrue(q.is_multi_answer)

    def test_next_level(self):
        bronze, silber, gold = create_levels()
        self.assertEqual(bronze.next_level, silber)
        self.assertEqual(silber.next_level, gold)
        self.assertIsNone(gold.next_level)

    def test_site_settings_singleton(self):
        first = SiteSettings.get()
        second = SiteSettings.get()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(SiteSettings.objects.count(), 1)
        self.assertEqual(first.training_pass_threshold, 75)


class LaFilterContextProcessorTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        create_levels()

    def _request(self, user=None, session=None):
        request = self.factory.get('/')
        request.session = session if session is not None else {}
        request.user = user or mock.Mock(is_authenticated=False)
        return request

    def test_defaults_to_first_level(self):
        request = self._request()
        self.assertEqual(la_filter(request)['la_filter'], 'bronze')
        self.assertEqual(request.session['la_filter'], 'bronze')

    def test_keeps_valid_session_value(self):
        request = self._request(session={'la_filter': 'gold'})
        self.assertEqual(la_filter(request)['la_filter'], 'gold')

    def test_invalid_session_value_is_replaced(self):
        request = self._request(session={'la_filter': 'platin'})
        self.assertEqual(la_filter(request)['la_filter'], 'bronze')

    def test_uses_next_level_after_divera_qualification(self):
        user = create_user()
        user.profile.divera_qualifications = [30132]  # LA Bronze
        user.profile.save()
        request = self._request(user=user)
        self.assertEqual(la_filter(request)['la_filter'], 'silber')

    def test_highest_level_stays(self):
        user = create_user()
        user.profile.divera_qualifications = [30134]  # LA Gold
        user.profile.save()
        request = self._request(user=user)
        self.assertEqual(la_filter(request)['la_filter'], 'gold')

    def test_admin_access_flag(self):
        user = create_user()
        self.assertFalse(la_filter(self._request(user=user))['user_has_admin_access'])
        user.user_permissions.add(Permission.objects.get(codename='access_admin'))
        user = User.objects.get(pk=user.pk)  # Berechtigungs-Cache leeren
        self.assertTrue(la_filter(self._request(user=user))['user_has_admin_access'])
