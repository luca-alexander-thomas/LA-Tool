"""Löschkonzept: abgelaufene Daten löschen (Fristen in app/legal_info.py, RETENTION).

- Trainingsergebnisse älter als RETENTION['training_days']
- Prüfungsergebnisse älter als RETENTION['exam_days']
- Konten, die wegen Austritts aus dem Divera-Standort gesperrt sind, RETENTION['left_account_days'] nach dem
  Austritt (mit allen zugehörigen Daten: Ergebnisse, Merkliste, Push-Abos, Benachrichtigungen …)
- Benachrichtigungen älter als RETENTION['notification_days'], erledigte Fehlermeldungen älter als
  RETENTION['resolved_report_days']

Für einen täglichen systemd-Timer gedacht; zuerst mit --dry-run prüfen.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from app.legal_info import RETENTION
from app.models import ExamResultData, QuestionReport, TrainingResultData
from la_tool_admin.models import UserNotification


class Command(BaseCommand):
    help = 'Löscht Daten nach Ablauf der Aufbewahrungsfristen (Löschkonzept).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Nur zählen, nichts löschen.')

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()

        def older(days):
            return now - timedelta(days=days)

        targets = [
            ('Trainingsergebnisse', TrainingResultData.objects.filter(meta_time__lt=older(RETENTION['training_days']))),
            ('Prüfungsergebnisse', ExamResultData.objects.filter(meta_time__lt=older(RETENTION['exam_days']))),
            ('Benachrichtigungen', UserNotification.objects.filter(created_at__lt=older(RETENTION['notification_days']))),
            ('Erledigte Fehlermeldungen', QuestionReport.objects.filter(
                resolved_at__lt=older(RETENTION['resolved_report_days']))),
            # Nur wegen Austritt gesperrte Konten; von Admins gesperrte (ohne divera_left_at) bleiben
            ('Konten nach Austritt', User.objects.filter(
                is_active=False, profile__divera_left_at__lt=older(RETENTION['left_account_days']))),
        ]
        prefix = '[Probelauf] ' if dry_run else ''
        with transaction.atomic():
            for label, qs in targets:
                count = qs.count()
                if label == 'Konten nach Austritt' and count:
                    names = ', '.join(qs.values_list('username', flat=True)[:20])
                    self.stdout.write(f'{prefix}{label}: {count} ({names})')
                else:
                    self.stdout.write(f'{prefix}{label}: {count}')
                if count and not dry_run:
                    qs.delete()
        self.stdout.write(self.style.SUCCESS(f'{prefix}Fertig.'))
