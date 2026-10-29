import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Levels, Questions_Catalogs, Questions_Theory, TrainingResultData


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
