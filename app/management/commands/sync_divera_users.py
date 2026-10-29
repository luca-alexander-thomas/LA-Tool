"""Divera-Konten abgleichen: Qualifikationen/Gruppen aktualisieren, Ausgetretene sperren, Gruppen neu berechnen.

Nutzt den Admin-API-Key (DIVERA_ADMIN_USER_API_KEY) für die Personenliste des Standorts (cluster.consumer).
Die Liste enthält nicht zwingend alle Mitglieder (z.B. keine reinen Verwaltungskonten). Fehlt jemand darin,
wird deshalb mit dessen eigenem Divera-Token nachgeprüft; gesperrt wird nur, wenn Divera eindeutig meldet,
dass die Person nicht mehr im Standort ist. Für den Cron/systemd-Timer gedacht.
"""
import requests
from django.core.management.base import BaseCommand

import la_tool.env as env
from app.login_function import (
    DiveraError, _divera_pull, _store_divera_cluster_quals, deactivate_divera_user, divera_error_text,
    divera_member_data,
)
from la_tool_admin.models import Profile
from la_tool_admin.utils import sync_idp_groups


class Command(BaseCommand):
    help = 'Divera-Konten abgleichen und ausgetretene Mitglieder sperren'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Nur anzeigen, nichts ändern')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        api_key = env.DIVERA_ADMIN_USER_API_KEY
        if not api_key:
            self.stderr.write(self.style.ERROR('DIVERA_ADMIN_USER_API_KEY fehlt in der .env.'))
            return

        members = self._site_members(api_key)
        if members is None:
            return
        if not members:
            # Leere Liste wäre ein API-Problem – sonst würden alle Konten gesperrt
            self.stderr.write(self.style.ERROR('Divera lieferte keine Mitglieder – Abbruch ohne Änderungen.'))
            return

        updated = deactivated = unclear = 0
        profiles = Profile.objects.filter(login_source=Profile.SOURCE_DIVERA, divera_ucr__isnull=False)
        for profile in profiles.select_related('user'):
            member = members.get(str(profile.divera_ucr))
            name = profile.user.username
            if member is None:
                status, member = self._check_with_own_token(profile)
                if status == 'left':
                    if profile.user.is_active:
                        self.stdout.write(f'Gesperrt (nicht mehr im Standort): {name}')
                        deactivated += 1
                        if not dry_run:
                            deactivate_divera_user(profile)
                    continue
                if status == 'unclear':
                    self.stdout.write(f'Nicht prüfbar (kein gültiger Divera-Token): {name}')
                    unclear += 1
                    continue

            if dry_run:
                continue
            profile.divera_qualifications = member.get('qualifications', [])
            profile.divera_groups = member.get('groups', [])
            profile.save(update_fields=['divera_qualifications', 'divera_groups'])
            sync_idp_groups(profile.user)
            updated += 1

        prefix = '[Probelauf] ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}{updated} aktualisiert, {deactivated} gesperrt, {unclear} nicht prüfbar.'))

    def _check_with_own_token(self, profile):
        """('member', daten) | ('left', None) | ('unclear', None) – Prüfung mit dem Token der Person."""
        if not profile.divera_api_key:
            return 'unclear', None
        try:
            data = divera_member_data(profile.divera_api_key)
        except DiveraError as exc:
            return ('left' if exc.kind == 'not_member' else 'unclear'), None
        if data['ucr'] != profile.divera_ucr:
            return 'unclear', None
        return 'member', data

    def _site_members(self, api_key):
        """{ucr: consumer-Daten} aller Mitglieder des Standorts oder None bei Fehlern."""
        site_id = str(env.DIVERA_Site_ID)
        try:
            initial = _divera_pull(api_key)
            ucr_data = (initial.get('data') or {}).get('ucr') or {}
            own_ucr = next((key for key, item in ucr_data.items()
                            if isinstance(item, dict) and str(item.get('cluster_id')) == site_id), None)
            if own_ucr is None:
                self.stderr.write(self.style.ERROR(f'Admin-Key gehört nicht zum Standort {site_id}.'))
                return None
            site = _divera_pull(api_key, ucr_id=own_ucr)
        except requests.RequestException as exc:
            self.stderr.write(self.style.ERROR(f'Divera nicht erreichbar: {divera_error_text(exc)}'))
            return None
        if not site.get('success'):
            self.stderr.write(self.style.ERROR('Divera lieferte success=false.'))
            return None
        cluster = (site.get('data') or {}).get('cluster') or {}
        _store_divera_cluster_quals(cluster)
        consumers = cluster.get('consumer') or {}
        return {str(k): v for k, v in consumers.items() if isinstance(v, dict)} if isinstance(consumers, dict) else {}
