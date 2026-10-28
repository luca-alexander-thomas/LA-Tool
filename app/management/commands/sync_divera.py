from datetime import datetime, timezone
import requests
from django.core.management.base import BaseCommand
from la_tool import env
from app.models import Work


def _divera_pull(access_token, ucr_id=None, timeout=30):
    url = f'https://app.divera247.com/api/v2/pull/all?accesskey={access_token}'
    if ucr_id is not None:
        url += f'&ucr={ucr_id}'
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class Command(BaseCommand):
    help = 'Sync Dienste (events) from Divera 24/7 API'

    def handle(self, *args, **options):
        api_key = env.DIVERA_ADMIN_USER_API_KEY
        if not api_key:
            self.stderr.write(self.style.ERROR(
                'DIVERA_ADMIN_USER_API_KEY is not set. Add it to your .env file.'
            ))
            return

        expected_site_id = str(env.DIVERA_Site_ID)
        self.stdout.write(f'Fetching UCR list from Divera (site {expected_site_id})...')

        # Step 1: Find the UCR that belongs to our configured site
        try:
            initial = _divera_pull(api_key)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Divera API request failed: {e}'))
            return

        if not initial.get('success'):
            self.stderr.write(self.style.ERROR(f'Divera returned success=false'))
            return

        ucr_data = initial.get('data', {}).get('ucr', {})
        matched_ucr_id = None
        for ucr_id_str, item in ucr_data.items():
            if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id:
                matched_ucr_id = ucr_id_str
                break

        if matched_ucr_id is None:
            self.stderr.write(self.style.ERROR(
                f'No UCR found for site {expected_site_id}. '
                f'Available cluster IDs: '
                f'{[v.get("cluster_id") for v in ucr_data.values() if isinstance(v, dict)]}'
            ))
            return

        self.stdout.write(f'Using UCR {matched_ucr_id} for site {expected_site_id}...')

        # Step 2: Pull with our site's UCR so data.events contains only our site's events
        try:
            site_data = _divera_pull(api_key, ucr_id=matched_ucr_id)
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f'Site-specific Divera request failed: {e}'))
            return

        if not site_data.get('success'):
            self.stderr.write(self.style.ERROR(f'Divera returned success=false for site pull'))
            return

        data = site_data.get('data', {})

        # Resolve the target group ID by name from the cluster group list
        target_group_name = env.DIVERA_EVENTS_GROUP
        group_map = data.get('cluster', {}).get('group', {})
        target_group_id = None
        for gid, ginfo in group_map.items():
            if isinstance(ginfo, dict) and ginfo.get('name') == target_group_name:
                target_group_id = int(gid)
                break

        if target_group_id is None:
            self.stderr.write(self.style.ERROR(
                f'Group "{target_group_name}" not found in cluster groups. '
                f'Available: {[v.get("name") for v in group_map.values() if isinstance(v, dict)]}'
            ))
            return

        self.stdout.write(f'Filtering events for group "{target_group_name}" (ID {target_group_id})...')

        events = self._find_events(data)

        if not events:
            self.stderr.write(self.style.WARNING(
                f'No events found for site {expected_site_id}. '
                f'Top-level data keys: {list(data.keys())}'
            ))
            return

        created = updated = skipped = 0
        for divera_id, event in events.items():
            event_groups = event.get('group') or []
            # Include if no group restriction (empty = all members) or explicitly targets our group
            if event_groups and target_group_id not in event_groups:
                skipped += 1
                continue
            title = (event.get('title') or event.get('name') or 'Dienst')[:100]
            start_ts = event.get('start') or event.get('date') or 0
            end_ts = event.get('end') or 0

            dt_start = self._ts_to_dt(start_ts)
            dt_end = self._ts_to_dt(end_ts) if end_ts else None

            location = (event.get('address') or event.get('location') or '')[:200]
            description = event.get('text') or event.get('description') or ''

            _, was_created = Work.objects.update_or_create(
                divera_id=str(divera_id),
                defaults={
                    'title': title,
                    'date': dt_start,
                    'date_end': dt_end,
                    'location': location,
                    'description': description,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Sync complete: {created} created, {updated} updated, {skipped} skipped (wrong group).'
        ))

    def _ts_to_dt(self, ts):
        try:
            return datetime.fromtimestamp(int(ts), tz=timezone.utc)
        except (ValueError, OSError, TypeError):
            return datetime.now(tz=timezone.utc)

    def _find_events(self, data):
        events_section = data.get('events', {})
        if isinstance(events_section, dict):
            items = events_section.get('items', {})
            if items:
                return items

        cluster = data.get('cluster', {})
        if cluster:
            items = cluster.get('appointments', {}).get('items', {})
            if items:
                return items

        appt = data.get('appointments', {})
        if appt:
            items = appt.get('items', appt)
            if isinstance(items, dict) and items:
                return items

        return None
