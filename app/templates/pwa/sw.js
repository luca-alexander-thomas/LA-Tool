// Service Worker des LA-Tools (gerendert von app/pwa.py)
//
// Strategie:
//  - Statische Dateien (CSS, JS, Bilder): aus dem Cache, im Hintergrund aktualisieren
//    (mit DEBUG zuerst vom Server, sonst sähe man Änderungen erst nach zweimaligem Neuladen)
//  - Seiten (HTML): immer vom Server, ohne Netz die Offline-Seite. Navigation Preload lädt die Seite
//    schon, während der Service Worker startet.
//  - Seiten werden bewusst NICHT gecacht: sie enthalten persönliche Daten und Prüfungen.
const CACHE = 'la-tool-{{ version }}';
const OFFLINE_URL = '{{ offline_url|escapejs }}';
const STATIC_PREFIX = '{{ static_prefix|escapejs }}';
const STATIC_NETWORK_FIRST = {{ static_network_first|yesno:"true,false" }};
const PRECACHE = [{% for url in precache %}'{{ url|escapejs }}'{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener('install', (event) => {
    event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)));
    self.skipWaiting();
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys()
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
            .then(() => self.registration.navigationPreload && self.registration.navigationPreload.enable())
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (request.mode === 'navigate') {
        event.respondWith((async () => {
            try {
                return (await event.preloadResponse) || (await fetch(request));
            } catch (e) {
                return caches.match(OFFLINE_URL);
            }
        })());
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
                    return STATIC_NETWORK_FIRST ? network.then((response) => response || cached) : cached || network;
                })
            )
        );
    }
});

// Web Push: Benachrichtigung anzeigen (Payload aus la_tool_admin/push.py: title, body, url)
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { body: event.data ? event.data.text() : '' };
    }
    event.waitUntil(
        self.registration.showNotification(data.title || 'LA-Tool', {
            body: data.body || '',
            icon: '{{ icon_url|escapejs }}',
            badge: '{{ badge_url|escapejs }}',
            data: { url: data.url || '/' },
        })
    );
});

// Antippen: vorhandenes App-Fenster nutzen, sonst neues öffnen
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const target = new URL(event.notification.data.url || '/', self.location.origin);
    if (target.origin !== self.location.origin) return;
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
            const win = windows.find((w) => 'focus' in w);
            if (win) return win.navigate(target.href).then((w) => (w || win).focus());
            return self.clients.openWindow(target.href);
        })
    );
});
