"""Progressive Web App: Manifest, Service Worker und Offline-Seite."""
from pathlib import Path

from django.contrib.staticfiles import finders
from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control


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
    # Neuer Cache-Name, sobald das Stylesheet neu gebaut wurde
    css = finders.find('css/tailwind.css')
    return int(Path(css).stat().st_mtime) if css else 0


@cache_control(no_cache=True)
def service_worker(request):
    context = {
        'version': _asset_version(),
        'offline_url': reverse('offline'),
        'static_prefix': static(''),
        'precache': [
            reverse('offline'),
            static('css/tailwind.css'),
            static('js/app.js'),
            static('vendor/alpine.min.js'),
            static('img/thw-jugend-ge-logo.png'),
            static('pwa/favicon.png'),
            static('pwa/icon-192.png'),
        ],
    }
    return render(request, 'pwa/sw.js', context, content_type='application/javascript')


def offline(request):
    return render(request, 'pwa/offline.html')
