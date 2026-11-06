// Service Worker des LA-Tools (gerendert von app/pwa.py)
//
// Strategie:
//  - Statische Dateien (CSS, JS, Bilder): aus dem Cache, im Hintergrund aktualisieren
//    (mit DEBUG zuerst vom Server, sonst sähe man Änderungen erst nach zweimaligem Neuladen)
//  - Seiten (HTML): immer vom Server, ohne Netz die Offline-Seite. Navigation Preload lädt die Seite
//    schon, während der Service Worker startet.
//  - Seiten werden bewusst NICHT gecacht: sie enthalten persönliche Daten und Prüfungen.
//  - Ausnahme Nachschlagen: Fragen mit Lösungen (ohne persönliche Daten) liegen als JSON im DATA_CACHE;
//    ohne Netz zeigt die Hülle OFFLINE_LOOKUP_URL sie an. Beim Abmelden löscht app.js den DATA_CACHE.
const CACHE = 'la-tool-{{ version }}';
const DATA_CACHE = 'la-tool-data';
const OFFLINE_URL = '{{ offline_url|escapejs }}';
const OFFLINE_LOOKUP_URL = '{{ offline_lookup_url|escapejs }}';
const OFFLINE_DATA_URL = '{{ offline_data_url|escapejs }}';
const LOOKUP_PREFIX = '{{ lookup_prefix|escapejs }}';
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
            .then((keys) => Promise.all(keys.filter((k) => k !== CACHE && k !== DATA_CACHE).map((k) => caches.delete(k))))
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
                const lookup = url.pathname.startsWith(LOOKUP_PREFIX) && (await caches.match(OFFLINE_DATA_URL));
                return caches.match(lookup ? OFFLINE_LOOKUP_URL : OFFLINE_URL);
            }
        })());
        return;
    }

    // Fragen zum Nachschlagen: immer frisch vom Server, ohne Netz der zuletzt gespeicherte Stand
    if (url.pathname === OFFLINE_DATA_URL) {
        event.respondWith(
            fetch(request)
                .then((response) => {
                    if (response.ok) {
                        const copy = response.clone();
                        caches.open(DATA_CACHE).then((cache) => cache.put(OFFLINE_DATA_URL, copy));
                    }
                    return response;
                })
                .catch(() => caches.match(OFFLINE_DATA_URL).then((cached) => cached || Response.error()))
        );
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

// Web Push: Benachrichtigung anzeigen (Payload aus la_tool_admin/push.py: title, body, url, unread, actions)
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = { body: event.data ? event.data.text() : '' };
    }
    const actions = Array.isArray(data.actions) ? data.actions : [];
    const jobs = [
        self.registration.showNotification(data.title || 'LA-Tool', {
            body: data.body || '',
            icon: '{{ icon_url|escapejs }}',
            badge: '{{ badge_url|escapejs }}',
            actions: actions.map((a) => ({ action: a.action, title: a.title })),
            data: { url: data.url || '/', actions },
        }),
    ];
    // Zahl am App-Symbol: ungelesene Benachrichtigungen
    if (typeof data.unread === 'number' && self.navigator.setAppBadge) {
        jobs.push(self.navigator.setAppBadge(data.unread).catch(() => {}));
    }
    event.waitUntil(Promise.all(jobs));
});

// Antippen: vorhandenes App-Fenster nutzen, sonst neues öffnen
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const data = event.notification.data || {};
    // Knopf in der Benachrichtigung (z.B. „Jetzt üben“) oder die Benachrichtigung selbst
    const action = (data.actions || []).find((a) => a.action === event.action);
    const target = new URL((action && action.url) || data.url || '/', self.location.origin);
    if (target.origin !== self.location.origin) return;
    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windows) => {
            const win = windows.find((w) => 'focus' in w);
            if (win) return win.navigate(target.href).then((w) => (w || win).focus());
            return self.clients.openWindow(target.href);
        })
    );
});
