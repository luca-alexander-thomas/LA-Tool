from django.contrib.auth.models import User
from django.contrib import auth
import logging

import requests
import la_tool.env as env
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from la_tool_admin.models import Profile

logger = logging.getLogger(__name__)


def divera_error_text(exc):
    """Fehlertext für Logs ohne URL: Divera-URLs enthalten den Access-Key als Query-Parameter."""
    response = getattr(exc, 'response', None)
    if response is not None:
        return f'HTTP {response.status_code}'
    return type(exc).__name__


def safe_next_url(request, url):
    """Rücksprung-Adresse nach dem Login, nur wenn sie auf diese Seite zeigt (kein Open Redirect)."""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()},
                                               require_https=request.is_secure()):
        return url
    return None


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
        logger.exception('Divera-Qualifikationen konnten nicht gespeichert werden')


def _divera_pull(access_token, ucr_id=None, timeout=30):
    params = {'accesskey': access_token}
    if ucr_id is not None:
        params['ucr'] = ucr_id
    resp = requests.get('https://app.divera247.com/api/v2/pull/all', params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


class DiveraError(Exception):
    """kind: 'unreachable' (Divera gestört), 'rejected' (abgelehnt), 'not_member' (nicht im Standort)."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind
        self.message = message


def divera_authenticate(username, password):
    """Meldet bei Divera an und gibt den Access-Token zurück (DiveraError bei Fehlern)."""
    try:
        response = requests.post(
            'https://www.divera247.com/api/v2/auth/login',
            json={'Login': {'username': username, 'password': password}},
            timeout=10,
        )
    except requests.RequestException:
        raise DiveraError('unreachable', 'Divera ist aktuell nicht erreichbar.')
    if response.status_code >= 500:
        raise DiveraError('unreachable', 'Divera ist aktuell nicht erreichbar.')
    try:
        data = response.json()
    except ValueError:
        raise DiveraError('unreachable', 'Ungültige Antwort von Divera.')
    if response.status_code != 200 or not isinstance(data, dict) or data.get('success') is not True:
        logger.info('Divera-Login abgelehnt: HTTP %s', response.status_code)
        raise DiveraError('rejected', 'Ungültige Divera-Zugangsdaten.')
    token = ((data.get('data') or {}).get('user') or {}).get('access_token')
    if not token:
        raise DiveraError('unreachable', 'Kein Divera Access Token erhalten.')
    return token


def divera_member_data(access_token):
    """Daten der Person im konfigurierten Standort: ucr, firstname, lastname, qualifications, groups."""
    expected_site_id = str(env.DIVERA_Site_ID)
    try:
        initial = _divera_pull(access_token)
    except requests.RequestException as exc:
        logger.warning('Divera-Abruf fehlgeschlagen: %s', divera_error_text(exc))
        raise DiveraError('unreachable', 'Divera-Benutzerdaten konnten nicht geladen werden.')
    if not isinstance(initial, dict) or not initial.get('success'):
        raise DiveraError('unreachable', 'Divera-Benutzerdaten konnten nicht geladen werden.')

    inner = initial.get('data') or {}
    ucr_data = inner.get('ucr') or {}
    if not isinstance(ucr_data, dict):
        raise DiveraError('unreachable', 'Ungültiges Format der Divera-Organisationsdaten.')
    matched = next((key for key, item in ucr_data.items()
                    if isinstance(item, dict) and str(item.get('cluster_id')) == expected_site_id), None)
    if matched is None or not str(matched).isdigit():
        raise DiveraError('not_member', 'Du bist nicht (mehr) dem DIVERA-Standort zugeordnet.')

    try:
        site_data = _divera_pull(access_token, ucr_id=matched)
    except requests.RequestException as exc:
        logger.warning('Divera-Standortabruf fehlgeschlagen: %s', divera_error_text(exc))
        raise DiveraError('unreachable', 'Divera-Standortdaten konnten nicht geladen werden.')
    if not isinstance(site_data, dict) or not site_data.get('success'):
        raise DiveraError('unreachable', 'Divera-Standortdaten konnten nicht geladen werden.')

    cluster_data = (site_data.get('data') or {}).get('cluster') or {}
    consumer = (cluster_data.get('consumer') or {}).get(str(matched)) or {}
    if not isinstance(consumer, dict):
        consumer = {}
    _store_divera_cluster_quals(cluster_data)
    user_info = inner.get('user') or {}
    return {
        'ucr': int(matched),
        'firstname': user_info.get('firstname', ''),
        'lastname': user_info.get('lastname', ''),
        'qualifications': consumer.get('qualifications', []),
        'groups': consumer.get('groups', []),
    }


def _apply_divera_data(profile, access_token, member):
    profile.divera_api_key = access_token
    profile.divera_ucr = member['ucr']
    profile.divera_qualifications = member['qualifications']
    profile.divera_groups = member['groups']
    profile.divera_left_at = None


def _ucr_taken_by_other(ucr, user):
    return Profile.objects.filter(divera_ucr=ucr).exclude(user=user).exists()


def refresh_divera_profile(profile):
    """Qualifikationen und Gruppen mit dem gespeicherten Token neu laden. True bei Erfolg."""
    if not profile.divera_api_key:
        return False
    try:
        member = divera_member_data(profile.divera_api_key)
    except DiveraError:
        return False
    if _ucr_taken_by_other(member['ucr'], profile.user):
        logger.warning('Divera-ID von %s ist bereits einem anderen Konto zugeordnet', profile.user.username)
        return False
    _apply_divera_data(profile, profile.divera_api_key, member)
    profile.save(update_fields=['divera_api_key', 'divera_ucr', 'divera_qualifications',
                                'divera_groups', 'divera_left_at'])
    return True


def _sync_groups(user):
    try:
        from la_tool_admin.utils import sync_idp_groups
        sync_idp_groups(user)
    except Exception:
        logger.exception('Fehler beim Gruppenabgleich für %s', user.username)


def post_login_setup(request, user):
    """Nach jedem Login: Divera-Daten auffrischen (falls verknüpft), Gruppen abgleichen, LA-Filter setzen."""
    from app.models import Levels
    profile = Profile.objects.filter(user=user).first()
    if profile is None:
        first_level = Levels.objects.filter(is_draft=False).order_by('order').first()
        request.session['la_filter'] = first_level.slug if first_level else ''
        return

    if profile.divera_api_key and profile.login_source != Profile.SOURCE_DIVERA:
        # Divera-Logins haben die Daten gerade erst geholt; Entra-/lokale Konten mit Verknüpfung hier
        refresh_divera_profile(profile)
        profile.refresh_from_db()

    current_la = profile.divera_la_level
    current_level = Levels.objects.filter(slug=current_la).first() if current_la else None
    if current_level:
        next_level = current_level.next_level or current_level
    else:
        next_level = Levels.objects.filter(is_draft=False).order_by('order').first()
    request.session['la_filter'] = next_level.slug if next_level else ''

    # Entra-Logins gleichen schon in sync_user_groups ab (mit frischen Entra-Gruppen)
    if profile.login_source != Profile.SOURCE_ENTRA:
        _sync_groups(user)


def link_divera_with_credentials(user, username, password):
    """Bestehendes Konto (z.B. Entra) mit Divera verknüpfen. True oder Fehlermeldung."""
    try:
        token = divera_authenticate(username, password)
        member = divera_member_data(token)
    except DiveraError as exc:
        return exc.message
    if _ucr_taken_by_other(member['ucr'], user):
        return 'Dieser Divera-Account ist bereits mit einem anderen Konto verknüpft.'
    profile, _ = Profile.objects.get_or_create(user=user)
    _apply_divera_data(profile, token, member)
    profile.save()
    _sync_groups(user)
    return True


def _is_divera_account(user):
    return Profile.objects.filter(user=user, login_source=Profile.SOURCE_DIVERA).exists()


def login(username, password, request):
    """Lokale Konten prüfen lokal, Divera-Konten immer gegen Divera.

    Das lokal gespeicherte Passwort eines Divera-Kontos gilt nur, wenn Divera nicht erreichbar ist.
    """
    username = (username or '').strip()
    local_user = auth.authenticate(request, username=username, password=password)
    if local_user is not None and not _is_divera_account(local_user):
        return local_user

    try:
        return divera_login(username, password, request)
    except DiveraError as exc:
        if exc.kind == 'unreachable' and local_user is not None:
            logger.warning('Divera nicht erreichbar: %s mit lokal gespeichertem Passwort angemeldet',
                           local_user.username)
            return local_user
        if exc.kind == 'not_member':
            _deactivate_left_member(username)
        request.session['login_error'] = exc.message
        return None


def deactivate_divera_user(profile):
    """Divera-Konto sperren, weil die Person nicht mehr im Standort ist (wird beim nächsten gültigen Login aufgehoben)."""
    profile.user.is_active = False
    profile.user.save(update_fields=['is_active'])
    profile.divera_left_at = timezone.now()
    profile.save(update_fields=['divera_left_at'])
    logger.info('Konto %s deaktiviert: nicht mehr im Divera-Standort', profile.user.username)


def _deactivate_left_member(username):
    """Divera-Zugangsdaten gültig, aber nicht mehr im Standort: zugehöriges Divera-Konto sperren."""
    profile = Profile.objects.filter(
        user__username__iexact=username, login_source=Profile.SOURCE_DIVERA,
    ).select_related('user').first()
    if profile and profile.user.is_active:
        deactivate_divera_user(profile)


def divera_login(username, password, request):
    """Divera-Anmeldung. Ordnet das Konto über die feste Divera-ID (UCR) zu, nie über den Namen allein."""
    token = divera_authenticate(username, password)
    member = divera_member_data(token)

    profile = Profile.objects.filter(divera_ucr=member['ucr']).select_related('user').first()
    if profile:
        user = profile.user
        if not user.is_active and profile.divera_left_at is None:
            # Von einem Admin gesperrt (nicht wegen Austritt): gesperrt lassen
            raise DiveraError('rejected', 'Dieses Konto ist deaktiviert.')
    else:
        user = User.objects.filter(username__iexact=username).first()
        if user is not None:
            # Gleicher Name, aber unbekannte Divera-ID: nur Altbestand aus Divera-Logins ohne ID übernehmen
            existing = Profile.objects.filter(user=user).first()
            if not existing or existing.login_source != Profile.SOURCE_DIVERA or existing.divera_ucr:
                logger.warning('Divera-Login für %s abgelehnt: Name gehört zu einem anderen Konto', username)
                raise DiveraError('rejected', 'Für diesen Benutzernamen gibt es bereits ein anderes Konto. '
                                              'Bitte an einen Admin wenden.')
        else:
            user = User(username=username.lower())

    user.email = user.email or username
    user.first_name = member['firstname']
    user.last_name = member['lastname']
    user.is_active = True
    # Nur als Notfall-Login, falls Divera ausfällt (siehe login())
    user.set_password(password)
    user.save()

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.login_source = Profile.SOURCE_DIVERA
    _apply_divera_data(profile, token, member)
    profile.save()

    _sync_groups(user)
    request.session.pop('login_error', None)
    return user


def apply_remember(request, remember):
    """Nach auth.login aufrufen: dauerhafte Sitzung (SESSION_COOKIE_AGE) oder bis zum Schließen des Browsers."""
    request.session['remember'] = bool(remember)
    request.session.set_expiry(None if remember else 0)


# ── Schutz vor Durchprobieren von Passwörtern ────────────────────────────────
# Zähler im Django-Cache (LocMem: je Gunicorn-Worker, die Grenze gilt also je Worker).
LOGIN_WINDOW = 15 * 60
LOGIN_MAX_PER_USER = 5     # Fehlversuche je Benutzername
LOGIN_MAX_PER_IP = 30      # Fehlversuche je IP (mehrere Personen hinter einem Router)


def client_ip(request):
    """IP des Aufrufers; hinter dem eigenen HTTPS-Proxy der von ihm angehängte letzte X-Forwarded-For-Eintrag."""
    from django.conf import settings
    if getattr(settings, 'SECURE_PROXY_SSL_HEADER', None):
        forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if forwarded:
            return forwarded.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def _login_keys(request, username):
    import hashlib
    name = hashlib.sha256(username.strip().lower().encode()).hexdigest()[:32]
    return f'login-fail:user:{name}', f'login-fail:ip:{client_ip(request)}'


def login_blocked(request, username):
    from django.core.cache import cache
    user_key, ip_key = _login_keys(request, username)
    return cache.get(user_key, 0) >= LOGIN_MAX_PER_USER or cache.get(ip_key, 0) >= LOGIN_MAX_PER_IP


def record_login_attempt(request, username, success):
    from django.core.cache import cache
    user_key, ip_key = _login_keys(request, username)
    if success:
        cache.delete(user_key)
        return
    for key in (user_key, ip_key):
        if cache.add(key, 1, LOGIN_WINDOW):
            continue
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOGIN_WINDOW)
    logger.warning('Fehlgeschlagene Anmeldung (IP %s)', client_ip(request))
