// Service Worker des LA-Tools (gerendert von app/pwa.py)
//
// Strategie:
//  - Statische Dateien (CSS, JS, Bilder): aus dem Cache, im Hintergrund aktualisieren
//  - Seiten (HTML): immer vom Server, ohne Netz die Offline-Seite
//  - Seiten werden bewusst NICHT gecacht: sie enthalten persönliche Daten und Prüfungen.
const CACHE = 'la-tool-{{ version }}';
const OFFLINE_URL = '{{ offline_url|escapejs }}';
const STATIC_PREFIX = '{{ static_prefix|escapejs }}';
const PRECACHE = [{% for url in precache %}'{{ url|escapejs }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === 'navigate') {
        event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
        return;
    }

    if (url.pathname.startsWith(STATIC_PREFIX)) {
        event.respondWith(
            caches.open(CACHE).then((cache) =>
                cache.match(request).then((cached) => {
                    const network = fetch(request)
                        .then((response) => {
                            if (response.ok) cache.put(request, response.clone());
                            return response;
                        })
                        .catch(() => cached);
                    return cached || network;
                })
            )
        );
    }
});
