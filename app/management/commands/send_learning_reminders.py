"""Wöchentliche Push-Erinnerung an fällige Wiederholungen im Theorie-Training.

Für einen systemd-Timer gedacht, z. B. sonntags 18 Uhr (siehe Readme). Erinnert nur Personen mit Push auf
mindestens einem Gerät, eingeschalteter Lern-Erinnerung (Profil) und mindestens einer fälligen Frage –
und jede Person höchstens einmal in MIN_GAP, auch wenn der Befehl öfter läuft.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from app import learning
from la_tool_admin.models import Profile
from la_tool_admin.push import push_configured, send_push

MIN_GAP = timedelta(days=6)


class Command(BaseCommand):
    help = 'Schickt eine Push-Erinnerung an alle, bei denen Theoriefragen zur Wiederholung fällig sind.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Nur anzeigen, wer erinnert würde.')

    def handle(self, *args, dry_run=False, **options):
        if not dry_run and not push_configured():
            self.stderr.write('Web Push ist nicht konfiguriert (VAPID_* fehlt) – nichts gesendet.')
            return

        now = timezone.now()
        users = list(User.objects.filter(is_active=True, push_subscriptions__isnull=False).filter(
            Q(profile__isnull=True) | Q(profile__learning_reminders=True),
        ).filter(
            Q(profile__isnull=True) | Q(profile__last_learning_reminder_at__isnull=True)
            | Q(profile__last_learning_reminder_at__lt=now - MIN_GAP),
        ).distinct())
        question_ids = list(learning.published_theory().values_list('pk', flat=True))
        attempts = learning.attempts_by_user([u.pk for u in users])
        today = timezone.localdate()

        reminded = 0
        for user in users:
            due = len(learning.due_questions(question_ids, attempts.get(user.pk, {}), today))
            if not due:
                continue
            if dry_run:
                self.stdout.write(f'{user.username}: {due} fällig')
                reminded += 1
                continue
            sent = send_push(
                [user],
                title='Zeit für eine Wiederholung',
                body=f'{due} Frage{"n" if due != 1 else ""} zur Wiederholung fällig – ein paar Minuten üben?',
                url=reverse('home'),
                actions=[{'action': 'practice', 'title': 'Jetzt üben', 'url': reverse('training_today')}],
            )
            if sent:
                Profile.objects.update_or_create(user=user, defaults={'last_learning_reminder_at': now})
                reminded += 1

        verb = 'würden erinnert' if dry_run else 'erinnert'
        self.stdout.write(self.style.SUCCESS(f'{reminded} von {len(users)} möglichen Personen {verb}.'))
