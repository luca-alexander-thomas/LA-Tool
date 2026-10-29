import json
import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import ExamResultData, Exams, Levels, Questions_Catalogs, Questions_Theory, TrainingResultData
from .views import EXAM_SUBMIT_GRACE_SEC


class TrainingRunTests(TestCase):
    """Theorie-Training: Fragen gehen ohne Lösung an den Browser, Abgabe und Bewertung auf dem Server."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        self.catalog = Questions_Catalogs.objects.create(
            title='Katalog', short_title='KAT', level=level,
            multi_answer_scoring=Questions_Catalogs.SCORING_PARTIAL,
        )
        self.single = Questions_Theory.objects.create(
            number='1', question='Einfach?', catalog=self.catalog, answer_text='Ja',
            answer_choice=['Nein', 'Ja', 'Vielleicht'],
        )
        # Fünf Antwortmöglichkeiten: e muss genauso gewertet werden wie a–d
        self.multi = Questions_Theory.objects.create(
            number='2', question='Mehrfach?', catalog=self.catalog, answer_text='',
            answer_correct=['A', 'E'], answer_choice=['A', 'B', 'C', 'D', 'E'],
        )
        self.client.force_login(self.user)

    def start(self):
        session = self.client.session
        session['training_question_ids'] = [self.single.pk, self.multi.pk]
        session.save()

    def test_run_sends_all_questions_without_solutions(self):
        self.start()
        response = self.client.get(reverse('training_run'))
        self.assertEqual(response.status_code, 200)
        questions = response.context['questions']
        self.assertEqual([q['id'] for q in questions], [self.single.pk, self.multi.pk])
        self.assertEqual(questions[0]['label'], 'KAT · 1')
        self.assertEqual(questions[1]['choices'][-1], ('e', 'E'))
        self.assertNotIn('correct', json.dumps(questions))

    def test_submit_scores_on_server_with_partial_points(self):
        self.start()
        answers = {str(self.single.pk): ['b'], str(self.multi.pk): ['a', 'z', 'b']}
        response = self.client.post(reverse('training_run'), {'answers': json.dumps(answers)})
        result = TrainingResultData.objects.get()
        self.assertRedirects(response, reverse('training_result', args=[result.pk]))
        # Einfach richtig = 1; Mehrfach: 1 richtig, 1 falsch von 2 → 0 Punkte; „z“ wird verworfen
        self.assertEqual(result.answers, {str(self.single.pk): ['b'], str(self.multi.pk): ['a', 'b']})
        self.assertEqual(result.meta_reference, {'score': 1.0, 'total': 2})
        self.assertNotIn('training_question_ids', self.client.session)

    def test_submit_with_garbage_counts_as_unanswered(self):
        self.start()
        self.client.post(reverse('training_run'), {'answers': 'kein json'})
        self.assertEqual(TrainingResultData.objects.get().meta_reference['score'], 0)

    def test_result_page_shows_all_choices(self):
        self.start()
        self.client.post(reverse('training_run'), {'answers': json.dumps({str(self.multi.pk): ['a', 'e']})})
        response = self.client.get(reverse('training_result', args=[TrainingResultData.objects.get().pk]))
        data = {d['question'].pk: d for d in response.context['questions_data']}
        self.assertTrue(data[self.multi.pk]['is_correct'])
        self.assertEqual(len(data[self.multi.pk]['labeled_choices']), 5)

    def test_run_without_session_redirects_to_config(self):
        self.assertRedirects(self.client.get(reverse('training_run')), reverse('training_config'))


class ExamRunTests(TestCase):
    """Prüfung: Fragen ohne Lösungen im Browser, Autosave, Abgabe mit Zeitprüfung auf dem Server."""

    def setUp(self):
        self.user = User.objects.create_user('pruefling', password='pw')
        level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        catalog = Questions_Catalogs.objects.create(title='Katalog', short_title='KAT', level=level)
        self.q1 = Questions_Theory.objects.create(
            question='Eins?', catalog=catalog, answer_text='Ja', answer_choice=['Nein', 'Ja'],
            help_reference='Geheimer Hinweis',
        )
        self.q2 = Questions_Theory.objects.create(
            question='Zwei?', catalog=catalog, answer_text='C', answer_choice=['A', 'B', 'C'],
        )
        self.exam = Exams.objects.create(name='Probe', time_in_min=10, pass_threshold=1, visible=True, closed=False)
        self.exam.questions.add(self.q1, self.q2)
        self.exam.assigned_users.add(self.user)
        self.client.force_login(self.user)
        self.client.post(reverse('exam_start', args=[self.exam.pk]))
        self.run_url = reverse('exam_run', args=[self.exam.pk])

    def set_started(self, seconds_ago):
        session = self.client.session
        session[f'exam_{self.exam.pk}_started_at'] = int(time.time()) - seconds_ago
        session.save()

    def test_page_contains_questions_without_solutions_or_hints(self):
        response = self.client.get(self.run_url)
        self.assertEqual(response.status_code, 200)
        payload = json.dumps(response.context['questions'])
        self.assertIn('Eins?', payload)
        self.assertNotIn('Geheimer Hinweis', payload)
        self.assertNotIn('correct', payload)

    def test_autosave_then_submit(self):
        save = self.client.post(self.run_url, {'action': 'save', 'answers': json.dumps({str(self.q1.pk): ['b']})})
        self.assertEqual(save.json(), {'ok': True})
        self.assertEqual(self.client.session[f'exam_{self.exam.pk}_answers'][str(self.q1.pk)], ['b'])
        # Neu laden: der Server liefert den gesicherten Stand mit
        self.assertEqual(self.client.get(self.run_url).context['saved_answers'][str(self.q1.pk)], ['b'])

        answers = {str(self.q1.pk): ['b'], str(self.q2.pk): ['c']}
        response = self.client.post(self.run_url, {'answers': json.dumps(answers)})
        self.assertRedirects(response, reverse('exam_result', args=[self.exam.pk]), fetch_redirect_response=False)
        result = ExamResultData.objects.get()
        self.assertEqual(result.meta_reference['score'], 2)
        self.assertTrue(result.meta_reference['passed'])
        self.assertNotIn(f'exam_{self.exam.pk}_question_ids', self.client.session)

    def test_late_submit_uses_last_autosave(self):
        self.client.post(self.run_url, {'action': 'save', 'answers': json.dumps({str(self.q1.pk): ['a']})})
        self.set_started(10 * 60 + EXAM_SUBMIT_GRACE_SEC + 5)
        self.assertEqual(self.client.post(self.run_url, {'action': 'save', 'answers': '{}'}).status_code, 409)
        self.client.post(self.run_url, {'answers': json.dumps({str(self.q1.pk): ['b'], str(self.q2.pk): ['c']})})
        result = ExamResultData.objects.get()
        self.assertEqual(result.answers, {str(self.q1.pk): ['a'], str(self.q2.pk): []})
        self.assertEqual(result.meta_reference['score'], 0)

    def test_submit_within_grace_counts(self):
        self.set_started(10 * 60 + 5)
        self.client.post(self.run_url, {'answers': json.dumps({str(self.q2.pk): ['c']})})
        self.assertEqual(ExamResultData.objects.get().meta_reference['score'], 1)

    def test_expired_page_view_finishes_exam(self):
        self.set_started(10 * 60 + EXAM_SUBMIT_GRACE_SEC + 5)
        response = self.client.get(self.run_url)
        self.assertRedirects(response, reverse('exam_result', args=[self.exam.pk]), fetch_redirect_response=False)
        self.assertEqual(ExamResultData.objects.count(), 1)
