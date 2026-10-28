import requests
from django.core.management.base import BaseCommand
from la_tool_admin.models import Profile
import la_tool.env as env


def _divera_pull(access_token, ucr_id=None, timeout=30):
    url = f'https://app.divera247.com/api/v2/pull/all?accesskey={access_token}'
    if ucr_id is not None:
        url += f'&ucr={ucr_id}'
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class Command(BaseCommand):
    help = 'Sync Divera qualifications and groups for all Divera users'

    def handle(self, *args, **options):
        expected_site_id = str(env.DIVERA_Site_ID)
        profiles = Profile.objects.filter(
            login_source=Profile.SOURCE_DIVERA,
            divera_api_key__gt='',
        ).select_related('user')

        if not profiles.exists():
            self.stdout.write('No Divera users found.')
            return

        updated = failed = 0
        for profile in profiles:
            username = profile.user.username
            self.stdout.write(f'Syncing {username}...')

            try:
                # Step 1: Find UCR for our configured site
                initial = _divera_pull(profile.divera_api_key)
            except requests.RequestException as e:
                self.stderr.write(f'  API error for {username}: {e}')
                failed += 1
                continue

            if not initial.get('success'):
                self.stderr.write(f'  Divera returned success=false for {username}')
                failed += 1
                continue

            ucr_data = initial.get('data', {}).get('ucr', {})
            matched_ucr_id = None
            for ucr_id_str, item in ucr_data.items():
                if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id:
                    matched_ucr_id = ucr_id_str
                    break

            if matched_ucr_id is None:
                self.stderr.write(f'  No UCR for site {expected_site_id} found for {username}')
                failed += 1
                continue

            try:
                # Step 2: Pull with our site's UCR so data.cluster is definitely our cluster
                site_data = _divera_pull(profile.divera_api_key, ucr_id=matched_ucr_id)
            except requests.RequestException as e:
                self.stderr.write(f'  Site-specific API error for {username}: {e}')
                failed += 1
                continue

            if not site_data.get('success'):
                self.stderr.write(f'  Site pull returned success=false for {username}')
                failed += 1
                continue

            cluster_consumers = site_data.get('data', {}).get('cluster', {}).get('consumer', {})
            consumer_info = cluster_consumers.get(str(matched_ucr_id), {})

            profile.divera_ucr = int(matched_ucr_id) if matched_ucr_id.isdigit() else None
            profile.divera_qualifications = consumer_info.get('qualifications', [])
            profile.divera_groups = consumer_info.get('groups', [])
            profile.save(update_fields=['divera_ucr', 'divera_qualifications', 'divera_groups'])

            self.stdout.write(self.style.SUCCESS(
                f'  OK: ucr={profile.divera_ucr}, '
                f'quals={profile.divera_qualifications}, '
                f'groups={profile.divera_groups}'
            ))
            updated += 1

        self.stdout.write(self.style.SUCCESS(f'\nDone: {updated} updated, {failed} failed.'))
