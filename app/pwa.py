"""Progressive Web App: Manifest, Service Worker, Offline-Seite und Web-Push-Abos."""
import json
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from la_tool_admin.models import PushSubscription
from la_tool_admin.push import MAX_PUSH_DEVICES_PER_USER, is_push_service, send_push


# (Datei, Größe, form_factor, Beschriftung) – erzeugt aus einer Demo-Datenbank, ohne echte Namen
SCREENSHOTS = [
    ('uebungen-mobil', '780x1688', 'narrow', 'Heute lernen mit Lernerfolg'),
    ('training-mobil', '780x1688', 'narrow', 'Theoriefragen üben'),
    ('lernstand-desktop', '1280x800', 'wide', 'Mein Lernstand'),
]


def manifest(request):
    data = {
        'name': 'THW-Jugend LA-Tool',
        'short_name': 'LA-Tool',
        'description': 'Vorbereitung auf das Leistungsabzeichen der THW-Jugend Gelsenkirchen',
        'lang': 'de-DE',
        'id': reverse('home'),
        'start_url': reverse('home'),
        'scope': '/',
        'display': 'standalone',
        'orientation': 'portrait-primary',
        'background_color': '#f4f6fa',
        'theme_color': '#00337f',
        'categories': ['education'],
        'icons': [
            {'src': static('pwa/icon-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
            {'src': static('pwa/icon-maskable-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
            {'src': static('pwa/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
        # Für den erweiterten Installationsdialog (Android/Chrome)
        'screenshots': [
            {'src': static(f'pwa/screenshots/{name}.png'), 'sizes': size, 'type': 'image/png',
             'form_factor': factor, 'label': label}
            for name, size, factor, label in SCREENSHOTS
        ],
        'shortcuts': [
            {'name': 'Heute lernen', 'short_name': 'Heute lernen', 'url': reverse('training_today')},
            {'name': 'Theorie-Training', 'short_name': 'Theorie', 'url': reverse('training_config')},
            {'name': 'Prüfungen', 'short_name': 'Prüfungen', 'url': reverse('exam_list')},
            {'name': 'Dienste', 'short_name': 'Dienste', 'url': reverse('work')},
        ],
    }
    return JsonResponse(data, content_type='application/manifest+json',
                        json_dumps_params={'ensure_ascii': False})


def _asset_version():
    # Neuer Cache-Name, sobald Stylesheet oder App-Skript geändert wurden (alte Einträge werden dann gelöscht)
    paths = [finders.find(name) for name in ('css/tailwind.css', 'js/app.js')]
    return max((int(Path(p).stat().st_mtime) for p in paths if p), default=0)


def static_prefix():
    # Nicht static(''): mit Manifest-Storage gibt es für den leeren Pfad keinen Eintrag
    return settings.STATIC_URL if settings.STATIC_URL.startswith('/') else '/' + settings.STATIC_URL


@cache_control(no_cache=True)
def service_worker(request):
    context = {
        'version': _asset_version(),
        # Entwicklung: Dateinamen ohne Hash (gleiche URL nach Änderung) → immer zuerst vom Server laden
        'static_network_first': settings.DEBUG,
        'offline_url': reverse('offline'),
        'offline_lookup_url': reverse('theory_offline_page'),
        'offline_data_url': reverse('theory_offline_data'),
        'lookup_prefix': reverse('theory_lookup'),
        'static_prefix': static_prefix(),
        'icon_url': static('pwa/icon-192.png'),
        'badge_url': static('pwa/badge-96.png'),
        'precache': [
            reverse('offline'),
            reverse('theory_offline_page'),
            static('css/tailwind.css'),
            static('js/app.js'),
            static('vendor/alpine.min.js'),
            static('img/thw-jugend-ge-logo.webp'),
            static('pwa/favicon.png'),
            static('pwa/icon-192.png'),
        ],
    }
    return render(request, 'pwa/sw.js', context, content_type='application/javascript')


def offline(request):
    return render(request, 'pwa/offline.html')


# ── Web Push: Geräte an-/abmelden ────────────────────────────────────────────

def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@require_POST
def push_subscribe(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Nicht angemeldet.'}, status=401)
    data = _json_body(request) or {}
    keys = data.get('keys') if isinstance(data.get('keys'), dict) else {}
    endpoint = data.get('endpoint')
    p256dh, auth = keys.get('p256dh'), keys.get('auth')
    if not (isinstance(endpoint, str) and len(endpoint) <= 700 and is_push_service(endpoint)
            and isinstance(p256dh, str) and p256dh and isinstance(auth, str) and auth):
        return JsonResponse({'error': 'Ungültiges Abo.'}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh[:200],
            'auth': auth[:100],
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:300],
        },
    )
    # Höchstens N Geräte pro Nutzer: die ältesten Abos fallen weg
    stale = PushSubscription.objects.filter(user=request.user).order_by('-created_at')[MAX_PUSH_DEVICES_PER_USER:]
    PushSubscription.objects.filter(pk__in=list(stale.values_list('pk', flat=True))).delete()
    return JsonResponse({'ok': True})


@require_POST
def push_unsubscribe(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Nicht angemeldet.'}, status=401)
    endpoint = (_json_body(request) or {}).get('endpoint', '')
    PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({'ok': True})


@require_POST
def push_test(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Nicht angemeldet.'}, status=401)
    sent = send_push([request.user], 'Test-Benachrichtigung',
                     'Push-Benachrichtigungen funktionieren auf diesem Gerät.', reverse('profile'))
    if not sent:
        return JsonResponse({'error': 'Keine Benachrichtigung zugestellt.'}, status=502)
    return JsonResponse({'ok': True, 'sent': sent})
