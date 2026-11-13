"""Geführtes Lernen: Wiederholung, „Heute lernen“, Merken/Melden, Auswertung, Lernstand, Erinnerungen, Lernaufträge."""
import json
from datetime import datetime, timedelta
from io import StringIO
from unittest import mock

from django.contrib.auth.models import Group, Permission, User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import learning
from .models import (
    LearningAssignment, Levels, QuestionBookmark, QuestionReport, Questions_Catalogs, Questions_Theory,
    TrainingResultData,
)


def at(days_ago):
    """Zeitpunkt vor `days_ago` Tagen (12 Uhr Ortszeit)."""
    day = timezone.localdate() - timedelta(days=days_ago)
    return timezone.make_aware(datetime(day.year, day.month, day.day, 12))


class LearningBase(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('jugend', first_name='Jule')
        self.client.force_login(self.user)
        self.level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99, default_training_count=3)
        self.cat_a = Questions_Catalogs.objects.create(title='Alpha', short_title='A', level=self.level, order=1)
        self.cat_b = Questions_Catalogs.objects.create(title='Beta', short_title='B', level=self.level, order=2)
        self.qa = [self.question(self.cat_a, i) for i in range(3)]
        self.qb = [self.question(self.cat_b, i) for i in range(3)]
        session = self.client.session
        session['la_filter'] = 'teststufe'
        session.save()

    def question(self, catalog, i):
        return Questions_Theory.objects.create(question=f'{catalog.short_title}{i}', number=str(i), catalog=catalog,
                                               answer_text='Ja', answer_choice=['Ja', 'Nein'])

    def train(self, results, days_ago=0, user=None):
        """results: {Frage: True/False}"""
        result = TrainingResultData.objects.create(
            name='T', user=user or self.user, questions=[q.pk for q in results],
            answers={str(q.pk): ['a'] if ok else ['b'] for q, ok in results.items()})
        TrainingResultData.objects.filter(pk=result.pk).update(meta_time=at(days_ago))
        result.refresh_from_db()
        return result


class ScheduleTests(LearningBase):
    def test_boxes_and_due_dates(self):
        today = timezone.localdate()
        self.assertEqual(learning.schedule([]), (0, None))
        # richtig → Fach 1, fällig morgen; nochmal richtig am selben Tag zählt nicht als Aufstieg
        self.assertEqual(learning.schedule([(at(0), 1.0), (at(0), 1.0)]), (1, today + timedelta(days=1)))
        # richtig, nach 1 Tag wieder richtig → Fach 2 (3 Tage)
        self.assertEqual(learning.schedule([(at(1), 1.0), (at(0), 1.0)]), (2, today + timedelta(days=3)))
        # falsch (auch Teilpunkte) → zurück auf 0, sofort fällig
        self.assertEqual(learning.schedule([(at(5), 1.0), (at(0), 0.5)]), (0, today))
        # höchstes Fach bleibt bei 30 Tagen
        rows = [(at(d), 1.0) for d in (100, 90, 80, 60, 40, 5)]
        self.assertEqual(learning.schedule(rows)[0], len(learning.INTERVALS))

    def test_pick_today_due_then_new_with_priority(self):
        self.train({self.qa[0]: True}, days_ago=3)   # fällig (Fach 1, vor 2 Tagen fällig)
        self.train({self.qa[1]: True}, days_ago=0)   # nicht fällig, gefestigt
        self.train({self.qb[0]: False}, days_ago=0)  # falsch → fällig
        attempts = learning.user_attempts(self.user)
        ids = [q.pk for q in self.qa + self.qb]
        self.assertEqual(learning.pick_today(ids, attempts, 10),
                         [self.qa[0].pk, self.qb[0].pk, self.qa[2].pk, self.qb[1].pk, self.qb[2].pk])
        # Lernauftrag-Fragen zuerst (innerhalb fällig/neu)
        prio = {self.qb[0].pk, self.qb[2].pk}
        self.assertEqual(learning.pick_today(ids, attempts, 3, prio), [self.qb[0].pk, self.qa[0].pk, self.qb[2].pk])

    def test_readiness(self):
        catalogs = [(self.cat_a, {'total': 2, 'counts': {'new': 0}}), (self.cat_b, {'total': 2, 'counts': {'new': 2}})]
        self.assertEqual(learning.readiness({'total': 4, 'score': 80}, catalogs[:1], 75)['state'], 'green')
        yellow = learning.readiness({'total': 4, 'score': 80}, catalogs, 75)
        self.assertEqual(yellow['state'], 'yellow')
        self.assertIn('Noch kaum geübt: B.', yellow['hints'])
        self.assertEqual(learning.readiness({'total': 4, 'score': 40}, catalogs[:1], 75)['state'], 'red')
        self.assertIsNone(learning.readiness({'total': 0, 'score': 0}, [], 75))

    def test_natural_question_order(self):
        self.assertEqual(sorted(['B1-19', 'B1-2', 'B10-1', None, 'B1-3a'], key=learning.natural_key),
                         [None, 'B1-2', 'B1-3a', 'B1-19', 'B10-1'])

    def test_timeline_and_streak(self):
        self.train({self.qa[0]: True}, days_ago=2)
        self.train({self.qa[1]: True}, days_ago=0)
        timeline = learning.progress_timeline([q.pk for q in self.qa + self.qb], learning.user_attempts(self.user))
        self.assertEqual([v for _, v in timeline], [17, 33])
        today = timezone.localdate()
        self.assertEqual(learning.practice_streak({today, today - timedelta(days=1), today - timedelta(days=3)}), 2)
        self.assertEqual(learning.practice_streak({today - timedelta(days=1)}), 1)
        self.assertEqual(learning.practice_streak({today - timedelta(days=2)}), 0)


class TodayAndCatalogTests(LearningBase):
    def test_today_starts_round_in_catalog_order(self):
        response = self.client.post(reverse('training_today'))
        self.assertRedirects(response, reverse('training_run'))
        self.assertEqual(self.client.session['training_question_ids'], [q.pk for q in self.qa])

    def test_today_nothing_left(self):
        for q in self.qa + self.qb:
            self.train({q: True}, days_ago=0)
        response = self.client.post(reverse('training_today'), follow=True)
        self.assertContains(response, 'Für heute ist alles erledigt')

    def test_read_then_practice_catalog(self):
        response = self.client.post(reverse('training_today'), {'catalog': self.cat_b.pk})
        self.assertRedirects(response, reverse('training_run'))
        self.assertEqual(self.client.session['training_question_ids'], [q.pk for q in self.qb])
        # Katalog schon gefestigt: trotzdem üben (zufällig)
        for q in self.qb:
            self.train({q: True}, days_ago=0)
        self.client.post(reverse('training_today'), {'catalog': self.cat_b.pk})
        self.assertEqual(sorted(self.client.session['training_question_ids']), sorted(q.pk for q in self.qb))

    def test_pages_render(self):
        self.train({self.qa[0]: True, self.qa[1]: False}, days_ago=1)
        self.train({self.qa[0]: True}, days_ago=0)
        for name in ('home', 'training_config', 'theory_lookup'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'Heute lernen')
        self.assertContains(response, 'id="lernstand"')
        self.assertContains(response, 'Alle Fragen')
        self.assertIsNotNone(response.context['chart'])

    def test_catalogs_without_theory_questions_hidden(self):
        """Kataloge nur mit Praxisaufgaben oder nur mit Entwürfen erscheinen nicht beim Theorie-Training (Issue #5)."""
        from .models import Questions_Practical
        practical_only = Questions_Catalogs.objects.create(title='Nur Praxis', short_title='P', level=self.level, order=3)
        Questions_Practical.objects.create(question='Knoten', catalog=practical_only, number='1')
        drafts_only = Questions_Catalogs.objects.create(title='Nur Entwürfe', short_title='E', level=self.level, order=4)
        Questions_Theory.objects.create(question='E?', catalog=drafts_only, answer_text='Ja',
                                        answer_choice=['Ja'], is_draft=True)
        for anonymous in (False, True):
            if anonymous:
                self.client.logout()
                session = self.client.session
                session['la_filter'] = 'teststufe'
                session.save()
            response = self.client.get(reverse('training_config'))
            self.assertEqual([c.title for c in response.context['catalogs']], ['Alpha', 'Beta'])
            self.assertNotContains(response, 'Nur Praxis')
            self.assertNotContains(response, 'Noch keine Fragen')

    def test_anonymous_cannot_use_today(self):
        self.client.logout()
        response = self.client.post(reverse('training_today'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])


class BookmarkReportTests(LearningBase):
    def post_json(self, url, data):
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def test_bookmark_and_saved_mode(self):
        url = reverse('question_bookmark', args=[self.qa[1].pk])
        self.assertEqual(self.post_json(url, {'saved': True}).json(), {'saved': True})
        self.assertEqual(self.post_json(url, {'saved': True}).json(), {'saved': True})  # idempotent
        self.assertEqual(QuestionBookmark.objects.count(), 1)
        self.client.post(reverse('training_config'), {'catalogs': [self.cat_a.pk, self.cat_b.pk], 'mode': 'saved', 'count': 10})
        self.assertEqual(self.client.session['training_question_ids'], [self.qa[1].pk])
        self.assertEqual(self.post_json(url, {'saved': False}).json(), {'saved': False})
        self.assertFalse(QuestionBookmark.objects.exists())

    def test_bookmark_needs_login_and_published_question(self):
        self.qa[0].is_draft = True
        self.qa[0].save()
        self.assertEqual(self.post_json(reverse('question_bookmark', args=[self.qa[0].pk]), {'saved': True}).status_code, 404)
        self.client.logout()
        self.assertEqual(self.post_json(reverse('question_bookmark', args=[self.qa[1].pk]), {'saved': True}).status_code, 403)

    def test_report_and_admin_resolve(self):
        url = reverse('question_report', args=[self.qa[0].pk])
        self.assertEqual(self.post_json(url, {'message': '  '}).status_code, 400)
        self.assertEqual(self.post_json(url, {'message': 'Antwort B stimmt auch'}).json(), {'ok': True})
        report = QuestionReport.objects.get()
        self.assertEqual((report.user, report.message), (self.user, 'Antwort B stimmt auch'))

        # Admin ohne Recht: 403; mit manage_theory: Liste und erledigen
        self.assertEqual(self.client.get(reverse('admin_report_list')).status_code, 403)
        self.user.user_permissions.add(*Permission.objects.filter(codename__in=['access_admin', 'manage_theory']))
        self.assertContains(self.client.get(reverse('admin_report_list')), 'Antwort B stimmt auch')
        self.client.post(reverse('admin_report_resolve', args=[report.pk]))
        report.refresh_from_db()
        self.assertIsNotNone(report.resolved_at)

    def test_report_limit(self):
        for _ in range(20):
            QuestionReport.objects.create(question=self.qa[0], user=self.user, message='x')
        self.assertEqual(self.post_json(reverse('question_report', args=[self.qa[0].pk]), {'message': 'y'}).status_code, 429)


class ResultPageTests(LearningBase):
    def test_wrong_first_retry_and_delta(self):
        self.train({self.qa[0]: True}, days_ago=1)
        result = self.train({self.qa[0]: True, self.qa[1]: False, self.qa[2]: False}, days_ago=0)
        response = self.client.get(reverse('training_result', args=[result.pk]))
        self.assertEqual([d['question'] for d in response.context['wrong']], [self.qa[1], self.qa[2]])
        # vorher: qa0 = 1/6 → 17 %; nachher: qa0 1.0 + qa1 0 + qa2 0 → 17 % (unverändert)
        self.assertEqual((response.context['score_before'], response.context['score_after']), (17, 17))
        self.assertContains(response, '2 Fehler direkt nochmal üben')

        self.client.post(reverse('training_retry', args=[result.pk]))
        self.assertEqual(self.client.session['training_question_ids'], [self.qa[1].pk, self.qa[2].pk])

    def test_retry_only_own_results(self):
        other = User.objects.create_user('andere')
        result = self.train({self.qa[0]: False}, user=other)
        self.assertEqual(self.client.post(reverse('training_retry', args=[result.pk])).status_code, 404)


class ReminderTests(LearningBase):
    def setUp(self):
        super().setUp()
        from la_tool_admin.models import PushSubscription
        PushSubscription.objects.create(user=self.user, endpoint='https://fcm.googleapis.com/x', p256dh='p', auth='a')

    def test_reminds_only_with_due_questions_and_once_a_week(self):
        with mock.patch('app.management.commands.send_learning_reminders.push_configured', return_value=True), \
             mock.patch('app.management.commands.send_learning_reminders.send_push', return_value=1) as push:
            call_command('send_learning_reminders', stdout=StringIO())
            push.assert_not_called()  # nichts geübt → nichts fällig

            self.train({self.qa[0]: False}, days_ago=0)
            call_command('send_learning_reminders', stdout=StringIO())
            self.assertEqual(push.call_count, 1)
            self.assertIn('1 Frage zur Wiederholung', push.call_args.kwargs['body'])

            call_command('send_learning_reminders', stdout=StringIO())
            self.assertEqual(push.call_count, 1)  # nicht zweimal in einer Woche

    def test_profile_switch_disables_reminders(self):
        self.train({self.qa[0]: False}, days_ago=0)
        self.client.post(reverse('profile'), {'action': 'learning_reminders', 'learning_reminders': '0'})
        self.assertFalse(self.user.profile.learning_reminders)
        out = StringIO()
        call_command('send_learning_reminders', '--dry-run', stdout=out)
        self.assertIn('0 von 0', out.getvalue())


class AdminLearningTests(LearningBase):
    def setUp(self):
        super().setUp()
        self.trainer = User.objects.create_user('ausbilder')
        self.trainer.user_permissions.add(*Permission.objects.filter(
            codename__in=['access_admin', 'view_learning_progress', 'manage_assignments']))
        self.client.force_login(self.trainer)

    def test_overview_and_detail(self):
        self.train({self.qa[0]: True, self.qa[1]: False})
        response = self.client.get(reverse('admin_learning'), {'stufe': 'teststufe'})
        self.assertEqual([r['user'] for r in response.context['rows']], [self.user])  # Ausbilder ohne Übung ausgeblendet
        self.assertEqual(response.context['hidden'], 1)
        response = self.client.get(reverse('admin_learning_user', args=[self.user.pk]), {'stufe': 'teststufe'})
        self.assertEqual([w['question'] for w in response.context['weak_questions']], [self.qa[1]])

    def test_overview_needs_permission(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('admin_learning')).status_code, 403)

    def test_assignment_lifecycle(self):
        group = Group.objects.create(name='Jugend')
        self.user.groups.add(group)
        response = self.client.post(reverse('admin_assignment_create'), {
            'title': 'Alpha lernen', 'description': '', 'level': self.level.pk, 'target_pct': 60,
            'due_date': (timezone.localdate() + timedelta(days=5)).isoformat(), 'work': '',
            'catalog_ids': [self.cat_a.pk], 'group_ids': [group.pk],
        })
        assignment = LearningAssignment.objects.get()
        self.assertRedirects(response, reverse('admin_assignment_detail', args=[assignment.pk]))
        self.assertEqual(list(assignment.recipients()), [self.user])

        # Jugendliche sehen den Auftrag und üben ihn; „Heute lernen“ nimmt seine Fragen zuerst
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('home')), 'Alpha lernen')
        self.client.post(reverse('training_today'), {'assignment': assignment.pk})
        self.assertEqual(self.client.session['training_question_ids'], [q.pk for q in self.qa])
        self.train({self.qa[0]: True, self.qa[1]: True})
        self.client.force_login(self.trainer)
        response = self.client.get(reverse('admin_assignment_detail', args=[assignment.pk]))
        self.assertEqual(response.context['done_count'], 1)  # 2 von 3 → 67 % ≥ 60 %

    def test_assignment_hidden_from_others(self):
        assignment = LearningAssignment.objects.create(title='Nur für Jule', level=self.level)
        assignment.assigned_users.add(self.user)
        other = User.objects.create_user('andere')
        self.client.force_login(other)
        self.assertNotContains(self.client.get(reverse('home')), 'Nur für Jule')
        self.assertEqual(self.client.post(reverse('training_today'), {'assignment': assignment.pk}).status_code, 404)


class ChartLocalizationTests(LearningBase):
    def test_svg_coordinates_use_dot(self):
        self.train({self.qa[0]: True}, days_ago=3)
        self.train({self.qa[1]: True}, days_ago=0)
        html = self.client.get(reverse('home')).content.decode()
        svg = html[html.index('<svg viewBox'):html.index('</svg>')]
        import re
        self.assertFalse(re.search(r'(cx|cy|y1|y2)="\d+,\d', svg), svg[:300])
