import io
import json
import os
import shutil
import tempfile
import time

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import ExamAttempt, ExamResultData, Exams, Levels, Questions_Catalogs, Questions_Theory, TrainingResultData
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
        ExamAttempt.objects.filter(user=self.user, exam=self.exam).update(
            started_at=timezone.now() - timedelta(seconds=seconds_ago))

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
        self.assertEqual(ExamAttempt.objects.get().answers[str(self.q1.pk)], ['b'])
        # Neu laden: der Server liefert den gesicherten Stand mit
        self.assertEqual(self.client.get(self.run_url).context['saved_answers'][str(self.q1.pk)], ['b'])

        answers = {str(self.q1.pk): ['b'], str(self.q2.pk): ['c']}
        response = self.client.post(self.run_url, {'answers': json.dumps(answers)})
        self.assertRedirects(response, reverse('exam_result', args=[self.exam.pk]), fetch_redirect_response=False)
        result = ExamResultData.objects.get()
        self.assertEqual(result.meta_reference['score'], 2)
        self.assertTrue(result.meta_reference['passed'])
        self.assertFalse(ExamAttempt.objects.exists())

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


    def test_restart_and_relogin_keep_the_clock_running(self):
        self.set_started(300)
        self.client.post(reverse('exam_start', args=[self.exam.pk]))
        self.client.logout()
        self.client.force_login(self.user)
        self.client.post(reverse('exam_start', args=[self.exam.pk]))
        self.assertEqual(ExamAttempt.objects.count(), 1)
        remaining = self.client.get(self.run_url).context['time_remaining_sec']
        self.assertLessEqual(remaining, 10 * 60 - 300)

    def test_second_submit_creates_no_second_result(self):
        answers = {'answers': json.dumps({str(self.q1.pk): ['b']})}
        self.client.post(self.run_url, answers)
        response = self.client.post(self.run_url, answers)
        self.assertRedirects(response, reverse('exam_result', args=[self.exam.pk]), fetch_redirect_response=False)
        self.assertEqual(ExamResultData.objects.count(), 1)
        # Nach der Abgabe lässt sich die Prüfung nicht erneut starten
        self.client.post(reverse('exam_start', args=[self.exam.pk]))
        self.assertFalse(ExamAttempt.objects.exists())

    def test_archived_exam_cannot_be_started(self):
        ExamAttempt.objects.all().delete()
        Exams.objects.filter(pk=self.exam.pk).update(archived=True)
        self.assertEqual(self.client.post(reverse('exam_start', args=[self.exam.pk])).status_code, 404)


class IconShrinkTests(TestCase):
    """Hochgeladene Icons werden auf max. 160 px verkleinert und als WebP gespeichert."""

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)

    def upload(self, name='gold.png', size=(800, 600)):
        buffer = io.BytesIO()
        Image.new('RGBA', size, (200, 150, 0, 255)).save(buffer, 'PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def test_upload_is_shrunk_to_webp(self):
        level = Levels.objects.create(name='Gold', slug='gold-test', order=50, icon=self.upload())
        self.assertTrue(level.icon.name.startswith('levels/') and level.icon.name.endswith('.webp'))
        with Image.open(level.icon.path) as image:
            self.assertEqual(image.size, (160, 120))
        # Erneutes Speichern lässt die Datei in Ruhe
        name = level.icon.name
        level.save()
        self.assertEqual(level.icon.name, name)

    def test_existing_file_replaced_and_old_one_removed(self):
        catalog = Questions_Catalogs.objects.create(title='K', short_title='K')
        path = os.path.join(self.media, 'ICONs')
        os.makedirs(path)
        with open(os.path.join(path, 'alt.png'), 'wb') as f:
            f.write(self.upload().read())
        Questions_Catalogs.objects.filter(pk=catalog.pk).update(icon='ICONs/alt.png')
        catalog.refresh_from_db()
        catalog.save()
        self.assertEqual(catalog.icon.name, 'ICONs/alt.webp')
        self.assertFalse(os.path.exists(os.path.join(path, 'alt.png')))

    def test_shared_old_file_is_kept(self):
        path = os.path.join(self.media, 'ICONs')
        os.makedirs(path)
        with open(os.path.join(path, 'geteilt.png'), 'wb') as f:
            f.write(self.upload().read())
        a = Questions_Catalogs.objects.create(title='A', short_title='A')
        Questions_Catalogs.objects.create(title='B', short_title='B')
        Questions_Catalogs.objects.update(icon='ICONs/geteilt.png')
        a.refresh_from_db()
        a.save()
        self.assertTrue(os.path.exists(os.path.join(path, 'geteilt.png')))


class HardeningTests(TestCase):
    """Absicherungen aus dem Code-Review."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        self.client.force_login(self.user)

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get(reverse('logout')).status_code, 405)
        self.client.post(reverse('logout'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_push_only_to_known_push_services(self):
        body = {'endpoint': 'https://10.0.0.5/intern', 'keys': {'p256dh': 'k', 'auth': 'a'}}
        response = self.client.post(reverse('push_subscribe'), json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 400)
        body['endpoint'] = 'https://web.push.apple.com/abc'
        response = self.client.post(reverse('push_subscribe'), json.dumps(body), content_type='application/json')
        self.assertEqual(response.status_code, 200)

    def test_la_filter_does_not_redirect_to_other_sites(self):
        response = self.client.get(reverse('set_la_filter', args=['x']), HTTP_REFERER='https://evil.example/')
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)

    def test_training_ignores_draft_catalogs(self):
        level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        draft = Questions_Catalogs.objects.create(title='Geheim', short_title='G', level=level, is_draft=True)
        Questions_Theory.objects.create(question='Geheim?', catalog=draft, answer_text='Ja', answer_choice=['Ja', 'Nein'])
        session = self.client.session
        session['la_filter'] = 'teststufe'
        session.save()
        self.client.post(reverse('training_config'), {'catalogs': [draft.pk], 'count': 5})
        self.assertNotIn('training_question_ids', self.client.session)


class LookupAndPracticalListTests(TestCase):
    """Theoriefragen nachschlagen (mit Lösung, ohne Entwürfe) und Praxisliste nach Katalogen."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        self.client.force_login(self.user)
        self.level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        session = self.client.session
        session['la_filter'] = 'teststufe'
        session.save()

    def catalog(self, title, order, draft=False):
        return Questions_Catalogs.objects.create(title=title, short_title=title[:3], level=self.level,
                                                 order=order, is_draft=draft)

    def test_lookup_groups_by_catalog_order_and_marks_solutions(self):
        second, first = self.catalog('Zweiter', 2), self.catalog('Erster', 1)
        draft = self.catalog('Entwurf', 0, draft=True)
        Questions_Theory.objects.create(question='Z?', catalog=second, answer_text='Ja', answer_choice=['Nein', 'Ja'])
        Questions_Theory.objects.create(question='E?', catalog=first, answer_text='Ja', answer_choice=['Ja', 'Nein'])
        Questions_Theory.objects.create(question='Geheim?', catalog=draft, answer_text='Ja', answer_choice=['Ja'])
        response = self.client.get(reverse('theory_lookup'))
        sections = response.context['sections']
        self.assertEqual([c.title for c, _, _ in sections], ['Erster', 'Zweiter'])
        self.assertEqual(sections[1][1][0]['choices'], [('a', 'Nein', False), ('b', 'Ja', True)])
        self.assertNotContains(response, 'Geheim?')

    def test_lookup_requires_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('theory_lookup')).status_code, 302)

    def test_practical_list_grouped_by_catalog_order(self):
        from .models import Questions_Practical
        b, a = self.catalog('Bbb', 5), self.catalog('Aaa', 1)
        Questions_Practical.objects.create(question='P-B', catalog=b, number='1')
        Questions_Practical.objects.create(question='P-A', catalog=a, number='2')
        sections = self.client.get(reverse('practical_list')).context['sections']
        self.assertEqual([c.title for c, _ in sections], ['Aaa', 'Bbb'])
