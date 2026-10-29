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
from la_tool_admin.push import send_push


def manifest(request):
    data = {
        'name': 'THW-Jugend LA-Tool',
        'short_name': 'LA-Tool',
        'description': 'Vorbereitung auf das Leistungsabzeichen der THW-Jugend Gelsenkirchen',
        'lang': 'de-DE',
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
        'shortcuts': [
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
        'offline_url': reverse('offline'),
        'static_prefix': static_prefix(),
        'icon_url': static('pwa/icon-192.png'),
        'badge_url': static('pwa/badge-96.png'),
        'precache': [
            reverse('offline'),
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
        return json.loads(request.body or b'{}')
    except ValueError:
        return None


@require_POST
def push_subscribe(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Nicht angemeldet.'}, status=401)
    data = _json_body(request)
    keys = (data or {}).get('keys') or {}
    endpoint = (data or {}).get('endpoint', '')
    if not (endpoint.startswith('https://') and keys.get('p256dh') and keys.get('auth')) or len(endpoint) > 700:
        return JsonResponse({'error': 'Ungültiges Abo.'}, status=400)
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': keys['p256dh'][:200],
            'auth': keys['auth'][:100],
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:300],
        },
    )
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
