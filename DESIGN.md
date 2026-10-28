# LA-Tool Design-System (Branch `design-v2`)

Frontend-Stack: **Django-Templates + Tailwind CSS v4 + Alpine.js + PWA**. Kein Bootstrap, kein Node.js.

## Entwicklung

```bash
pip install -r requirements.txt
python manage.py tailwind runserver   # Django-Server + Tailwind-Watcher in einem
python manage.py tailwind build       # Stylesheet einmalig bauen (vor Deployment / collectstatic)
```

Beim ersten Aufruf lädt `django-tailwind-cli` die Tailwind-Standalone-Binary nach `.django_tailwind_cli/`.
Das gebaute Stylesheet `assets/css/tailwind.css` ist eingecheckt, damit der Branch auch ohne Build läuft.
**Nach Template-Änderungen mit neuen Klassen immer neu bauen.**

## Dateien

| Datei | Zweck |
|---|---|
| `tailwind/source.css` | Design-Tokens, Dark Mode, Komponenten-Klassen |
| `app/templates/base.html` | App-Shell: Kopfzeile, Desktop-Navigation, mobile Tab-Leiste, PWA-Tags |
| `la_tool_admin/templates/admin_base.html` | Admin-Shell mit Seitenleiste; Admin-Seiten füllen `{% block admin_content %}` |
| `app/templates/icons/*.html` | Heroicons als Includes: `{% include "icons/check.html" with cls="size-4" %}` |
| `app/static/js/app.js` | Farbschema-Umschalter (Alpine-Komponente `themeSwitcher`) |
| `app/pwa.py`, `app/templates/pwa/` | Web-Manifest, Service Worker (`/sw.js`), Offline-Seite |
| `app/context_processors.py` | `nav_section` markiert den aktiven Menüpunkt |

## Farben

Semantische Farben wechseln automatisch im Dark Mode (`<html data-theme="dark">`):

| Klasse | Verwendung |
|---|---|
| `bg-bg` | Seitenhintergrund |
| `bg-surface`, `bg-surface-2` | Karten, Flächen, Hover |
| `text-ink`, `text-ink-2`, `text-ink-3` | Text: primär, sekundär, dezent |
| `border-line` | Rahmen, Trennlinien |
| `bg-accent`, `text-accent-ink`, `bg-accent-soft` | THW-Blau: Buttons, Links, aktive Zustände |
| `thw-50` … `thw-900` | THW-Blau-Skala (z. B. Verläufe) |
| `jugend-orange`, `jugend-sky` | Akzentfarben aus dem THW-Jugend-Logo |

Für Erfolg/Fehler/Warnung die Tailwind-Paletten `green`, `red`, `amber`, `sky` jeweils mit `dark:`-Variante nutzen
oder direkt die Komponenten `badge-*` / `alert-*`.

Die Stufen-Badges (`Levels.badge_bg_class`, `badge_text_class`) kommen aus der Datenbank. Die Bootstrap-Namen
`bg-warning`, `text-dark`, `bg-secondary`, `text-white` usw. funktionieren weiter:
`<span class="badge {{ level.badge_bg_class|default:'badge-primary' }} {{ level.badge_text_class }}">`.

## Komponenten-Klassen

| Bereich | Klassen |
|---|---|
| Layout | `page` (Standardseite), `page-narrow` (Formulare, Quiz), `container-app`, `page-header`, `page-title`, `page-subtitle`, `eyebrow`, `section-title`, `back-link` |
| Karten | `card`, `card-body`, `card-header`, `card-footer`, `card-link` (klickbar), `list-row`, `empty-state`, `icon-tile`, `stat-value`, `stat-label`, `prose-content` |
| Buttons | `btn` + `btn-primary` / `btn-secondary` / `btn-ghost` / `btn-soft` / `btn-success` / `btn-danger` / `btn-danger-soft`, Größen `btn-sm`, `btn-lg`, `btn-icon` |
| Status | `badge` + `badge-neutral/primary/success/danger/warning/info`; `alert` + `alert-success/danger/warning/info` |
| Formulare | `form-label`, `form-control`, `form-select`, `form-check`, `form-check-input`, `form-check-label`, `form-switch` (Checkbox mit `role="switch"`), `form-text`, `form-error`, `input-group`, `input-group-text` |
| Tabellen | `table-wrap` > `table.table` |
| Sonstiges | `progress` > `progress-bar`, `tabs` > `tab` / `tab-active`, `dropdown-menu` > `dropdown-item` / `dropdown-divider`, `<dialog class="modal">` > `modal-header` / `modal-body` |
| Quiz | `label.answer-option` (enthält Checkbox/Radio; Zustand über `:has(:checked)` oder `is-selected`, `is-correct`, `is-wrong`) > `span.answer-letter` |

Die Formular-Klassen heißen wie in Bootstrap, damit die Widgets in `la_tool_admin/forms.py` unverändert passen.

## Interaktion (Alpine.js statt Bootstrap-JS)

```html
<!-- Aufklappen -->
<div x-data="{ open: false }">
  <button type="button" @click="open = !open" :aria-expanded="open">Details</button>
  <div x-show="open" x-cloak x-transition>…</div>
</div>

<!-- Tabs -->
<div x-data="{ tab: 'login' }">
  <div class="tabs" role="tablist">
    <button type="button" class="tab" :class="tab === 'login' && 'tab-active'" @click="tab = 'login'">Login</button>
  </div>
  <div x-show="tab === 'login'">…</div>
</div>

<!-- Modal (natives <dialog>) -->
<button type="button" class="btn btn-primary" onclick="document.getElementById('m').showModal()">Öffnen</button>
<dialog id="m" class="modal">
  <div class="modal-header"><h2 class="section-title">Titel</h2>
    <form method="dialog"><button class="btn btn-ghost btn-icon" aria-label="Schließen">…</button></form></div>
  <div class="modal-body">…</div>
</dialog>
```

Sicherheitsabfragen bleiben `onclick="return confirm('…')"`.

## Regeln

- Mobile first: alles muss ab 360 px Breite bedienbar sein, Touch-Ziele mindestens 44 px (`btn` erfüllt das).
- Breite Tabellen immer in `table-wrap` (horizontal scrollbar).
- Keine Inline-Styles außer für dynamische Werte (z. B. `style="width: {{ pct }}%"`).
- Seitentitel über `{% block page_title %}…{% endblock %}`.
