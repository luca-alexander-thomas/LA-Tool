from django.contrib.auth.models import User
from django.contrib import auth
import requests
import la_tool.env as env
from la_tool_admin.models import Profile


def _store_divera_cluster_quals(cluster_data):
    """Try to persist Divera qualification definitions from cluster-level API data."""
    try:
        from la_tool_admin.models import DiveraQualification
        cluster_quals = cluster_data.get('qualifications', {})
        if not isinstance(cluster_quals, dict):
            return
        for qid_str, qinfo in cluster_quals.items():
            try:
                qid = int(qid_str)
                if isinstance(qinfo, dict):
                    name = qinfo.get('name') or qinfo.get('title') or str(qid)
                    short_name = qinfo.get('short_name') or qinfo.get('shortname') or ''
                else:
                    name = str(qinfo)
                    short_name = ''
                DiveraQualification.objects.update_or_create(
                    qual_id=qid,
                    defaults={'name': name, 'short_name': short_name},
                )
            except (ValueError, Exception):
                pass
    except Exception:
        pass


def _divera_pull(access_token, ucr_id=None, timeout=30):
    url = f'https://app.divera247.com/api/v2/pull/all?accesskey={access_token}'
    if ucr_id is not None:
        url += f'&ucr={ucr_id}'
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def refresh_divera_profile(profile):
    """Re-fetch qualifications and groups from Divera using the stored API key.
    Updates profile in-place and saves. Returns True on success, False on failure.
    """
    if not profile.divera_api_key:
        return False

    expected_site_id = str(env.DIVERA_Site_ID)
    try:
        initial = _divera_pull(profile.divera_api_key)
    except requests.RequestException:
        return False

    if not initial.get('success'):
        return False

    ucr_data = initial.get('data', {}).get('ucr', {})
    matched_ucr_id = None
    for ucr_id_str, item in ucr_data.items():
        if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id:
            matched_ucr_id = ucr_id_str
            break

    if matched_ucr_id is None:
        return False

    try:
        site_data = _divera_pull(profile.divera_api_key, ucr_id=matched_ucr_id)
    except requests.RequestException:
        return False

    if not site_data.get('success'):
        return False

    cluster_data = site_data.get('data', {}).get('cluster', {})
    cluster_consumers = cluster_data.get('consumer', {})
    consumer_info = cluster_consumers.get(str(matched_ucr_id), {})

    profile.divera_ucr = int(matched_ucr_id) if matched_ucr_id.isdigit() else None
    profile.divera_qualifications = consumer_info.get('qualifications', [])
    profile.divera_groups = consumer_info.get('groups', [])
    profile.save(update_fields=['divera_ucr', 'divera_qualifications', 'divera_groups'])

    _store_divera_cluster_quals(cluster_data)
    return True


def post_login_setup(request, user):
    """Called after every successful login.
    Refreshes Divera data (if API key exists) and sets la_filter session default.
    """
    try:
        profile = user.profile
    except Exception:
        from app.models import Levels
        first_level = Levels.objects.order_by('order').first()
        request.session['la_filter'] = first_level.slug if first_level else ''
        return

    if profile.divera_api_key and profile.login_source != Profile.SOURCE_DIVERA:
        # Divera logins already refresh during authentication; others do it here
        refresh_divera_profile(profile)
        profile.refresh_from_db(fields=['divera_qualifications'])

    from app.models import Levels
    current_la = profile.divera_la_level
    if current_la:
        current_level = Levels.objects.filter(slug=current_la).first()
        if current_level:
            next_level = current_level.next_level or current_level
        else:
            next_level = Levels.objects.order_by('order').first()
    else:
        next_level = Levels.objects.order_by('order').first()
    request.session['la_filter'] = next_level.slug if next_level else ''

    # Sync auto-group memberships based on current Divera qualifications
    # (Entra group sync happens inside sync_user_groups during Entra login)
    if profile.login_source != Profile.SOURCE_ENTRA:
        try:
            from la_tool_admin.utils import sync_auto_groups
            sync_auto_groups(user, divera_qual_ids=profile.divera_qualifications or [])
        except Exception:
            pass


def link_divera_with_credentials(user, username, password):
    """
    Link an already-authenticated user to Divera using credentials.
    Returns True on success, or an error message string on failure.
    """
    try:
        auth_response = requests.post(
            'https://www.divera247.com/api/v2/auth/login',
            json={"Login": {"username": username, "password": password}},
            timeout=10,
        )
    except requests.RequestException:
        return 'Divera ist aktuell nicht erreichbar.'

    if auth_response.status_code != 200:
        return 'Divera-Login fehlgeschlagen.'

    try:
        auth_data = auth_response.json()
    except ValueError:
        return 'Ungültige Antwort von Divera.'

    if auth_data.get('success') is not True:
        return 'Ungültige Divera-Zugangsdaten.'

    access_token = auth_data.get('data', {}).get('user', {}).get('access_token')
    if not access_token:
        return 'Kein Divera Access Token erhalten.'

    expected_site_id = str(env.DIVERA_Site_ID)

    try:
        initial = _divera_pull(access_token)
    except requests.RequestException:
        return 'Divera-Benutzerdaten konnten nicht geladen werden.'

    if not initial.get('success'):
        return 'Divera-Benutzerdaten konnten nicht geladen werden.'

    ucr_data = initial.get('data', {}).get('ucr', {})
    matched_ucr_id = None
    for ucr_id_str, item in ucr_data.items():
        if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id:
            matched_ucr_id = ucr_id_str
            break

    if matched_ucr_id is None:
        return 'Dieser Divera-Account ist nicht dem konfigurierten Standort zugeordnet.'

    try:
        site_data = _divera_pull(access_token, ucr_id=matched_ucr_id)
    except requests.RequestException:
        return 'Divera-Standortdaten konnten nicht geladen werden.'

    if not site_data.get('success'):
        return 'Divera-Standortdaten konnten nicht geladen werden.'

    cluster_data = site_data.get('data', {}).get('cluster', {})
    cluster_consumers = cluster_data.get('consumer', {})
    consumer_info = cluster_consumers.get(str(matched_ucr_id), {})
    qualifications = consumer_info.get('qualifications', [])
    groups = consumer_info.get('groups', [])

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.divera_api_key = access_token
    profile.divera_ucr = int(matched_ucr_id) if matched_ucr_id.isdigit() else None
    profile.divera_qualifications = qualifications
    profile.divera_groups = groups
    profile.save()

    _store_divera_cluster_quals(cluster_data)

    try:
        from la_tool_admin.utils import sync_auto_groups
        sync_auto_groups(user, divera_qual_ids=qualifications)
    except Exception:
        pass

    return True


def login(username, password, request):
    print(f"Attempting to authenticate user: {username}")
    user = auth.authenticate(request, username=username, password=password)
    if user is not None:
        return user

    print(f"User {username} not found locally, trying Divera login.")
    return divera_login(username, password, request)


def divera_login(username, password, request):
    try:
        auth_response = requests.post(
            'https://www.divera247.com/api/v2/auth/login',
            json={"Login": {"username": username, "password": password}},
            timeout=10,
        )
    except requests.RequestException:
        request.session['login_error'] = 'Divera ist aktuell nicht erreichbar.'
        return None

    if auth_response.status_code != 200:
        print(f"Error logging in to Divera: {auth_response.status_code}")
        request.session['login_error'] = 'Divera-Login fehlgeschlagen.'
        return None

    try:
        auth_data = auth_response.json()
    except ValueError:
        request.session['login_error'] = 'Ungültige Antwort von Divera beim Login.'
        return None

    if auth_data.get('success') is not True:
        print("Divera login failed")
        request.session['login_error'] = 'Ungültige DIVERA Zugangsdaten.'
        return None

    access_token = auth_data.get('data', {}).get('user', {}).get('access_token')
    if not access_token:
        request.session['login_error'] = 'Kein Divera Access Token erhalten.'
        return None

    print(f"Divera Access Token: {access_token}")

    expected_site_id = str(env.DIVERA_Site_ID)

    # Step 1: Find the UCR belonging to our configured site
    try:
        initial = _divera_pull(access_token)
    except requests.RequestException:
        request.session['login_error'] = 'Divera-Benutzerdaten konnten nicht geladen werden.'
        return None

    if not initial.get('success'):
        request.session['login_error'] = 'Divera-Benutzerdaten konnten nicht geladen werden.'
        return None

    inner = initial.get('data', {})
    ucr_data = inner.get('ucr', {})
    firstname = inner.get('user', {}).get('firstname', '')
    lastname = inner.get('user', {}).get('lastname', '')

    if not isinstance(ucr_data, dict):
        request.session['login_error'] = 'Ungültiges Format der Divera-Organisationsdaten.'
        return None

    matched_ucr_id = None
    for ucr_id_str, item in ucr_data.items():
        if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id:
            matched_ucr_id = ucr_id_str
            break

    if matched_ucr_id is None:
        request.session['login_error'] = 'Du bist nicht dem konfigurierten DIVERA Standort zugeordnet.'
        return None

    # Step 2: Pull with our site's UCR so data.cluster is the right cluster
    try:
        site_data = _divera_pull(access_token, ucr_id=matched_ucr_id)
    except requests.RequestException:
        request.session['login_error'] = 'Divera-Standortdaten konnten nicht geladen werden.'
        return None

    if not site_data.get('success'):
        request.session['login_error'] = 'Divera-Standortdaten konnten nicht geladen werden.'
        return None

    cluster_data = site_data.get('data', {}).get('cluster', {})
    cluster_consumers = cluster_data.get('consumer', {})
    consumer_info = cluster_consumers.get(str(matched_ucr_id), {})
    qualifications = consumer_info.get('qualifications', [])
    groups = consumer_info.get('groups', [])

    print(f"UCR {matched_ucr_id}: quals={qualifications}, groups={groups}")

    user, _ = User.objects.get_or_create(username=username)
    user.email = username
    user.set_password(password)
    user.first_name = firstname
    user.last_name = lastname
    user.save()

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.login_source = Profile.SOURCE_DIVERA
    profile.divera_api_key = access_token
    profile.divera_ucr = int(matched_ucr_id) if matched_ucr_id.isdigit() else None
    profile.divera_qualifications = qualifications
    profile.divera_groups = groups
    profile.save()

    _store_divera_cluster_quals(cluster_data)

    try:
        from la_tool_admin.utils import sync_auto_groups
        sync_auto_groups(user, divera_qual_ids=qualifications)
    except Exception:
        pass

    if 'login_error' in request.session:
        del request.session['login_error']
    return user
