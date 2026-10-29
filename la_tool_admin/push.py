"""Web-Push-Benachrichtigungen an die PWA (VAPID, pywebpush)."""
import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from pywebpush import WebPushException, webpush

from .models import PushSubscription

logger = logging.getLogger(__name__)

# Nur echte Push-Dienste der Browser: sonst könnte jeder Nutzer den Server beliebige Adressen
# (auch im internen Netz) anfragen lassen, sobald Push verschickt wird.
PUSH_SERVICE_HOSTS = (
    'fcm.googleapis.com',            # Chrome, Edge (Android), Opera
    'push.services.mozilla.com',     # Firefox
    'notify.windows.com',            # Edge (Windows)
    'push.apple.com',                # Safari / iOS
)
MAX_PUSH_DEVICES_PER_USER = 10


def is_push_service(endpoint):
    parts = urlsplit(endpoint)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and parts.port in (None, 443) and any(
        host == h or host.endswith('.' + h) for h in PUSH_SERVICE_HOSTS)


# Abo existiert beim Push-Dienst nicht mehr (App deinstalliert, Berechtigung entzogen)
_GONE_STATUS = (404, 410)


def push_configured():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def send_push(users, title, body, url='/'):
    """Schickt eine Benachrichtigung an alle Geräte der Nutzer.

    Gibt die Anzahl erfolgreich zugestellter Geräte zurück. Abgelaufene Abos werden gelöscht,
    andere Fehler nur protokolliert – ein fehlgeschlagener Push darf keine Admin-Aktion abbrechen.
    """
    if not push_configured():
        logger.warning('Web Push nicht konfiguriert (VAPID_* fehlt) – nichts gesendet.')
        return 0

    payload = json.dumps({'title': title, 'body': body, 'url': url})
    sent = 0
    for sub in PushSubscription.objects.filter(user__in=users, user__is_active=True):
        if not is_push_service(sub.endpoint):
            continue  # Altbestand vor der Host-Prüfung: nicht anfragen
        try:
            webpush(
                subscription_info={'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}},
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={'sub': settings.VAPID_SUBJECT},
                ttl=24 * 60 * 60,
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, 'status_code', None)
            if status in _GONE_STATUS:
                sub.delete()
            else:
                logger.warning('Web Push an %s fehlgeschlagen (%s): %s', sub.user, status, exc)
        except Exception:
            logger.exception('Web Push an %s fehlgeschlagen', sub.user)
    return sent
