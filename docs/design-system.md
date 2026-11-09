# Design-System

Frontend-Stack: **Django-Templates + Tailwind CSS v4 + Alpine.js + PWA**. Kein Bootstrap, kein Node.js. Einrichtung und Build-Befehle: [Entwicklung](entwicklung.md#stylesheet-bauen).

Das gebaute Stylesheet `assets/css/tailwind.css` ist eingecheckt. **Nach Template-Änderungen mit neuen Klassen und nach Änderungen an `tailwind/source.css` immer `python manage.py tailwind build` ausführen und mit committen.**

## Dateien

| Datei | Zweck |
|---|---|
| `tailwind/source.css` | Design-Tokens, Dark Mode, Komponenten-Klassen |
| `app/templates/base.html` | App-Shell: Kopfzeile, Desktop-Navigation, mobile Tab-Leiste, PWA-Tags |
| `la_tool_admin/templates/admin_base.html` | Admin-Shell mit Seitenleiste; Admin-Seiten füllen `{% block admin_content %}` |
| `app/templates/icons/*.html` | Heroicons als Includes: `{% include "icons/check.html" with cls="size-4" %}` |
| `app/static/js/app.js` | Alpine-Komponenten (u.&nbsp;a. `themeSwitcher`, `questionRun` für Training/Prüfung, `questionActions`, `pushToggle`, `pushPrompt`, `installPrompt`, `toastStack`, `connection`), Rückmeldung bei Aktionen (`pageFeedback`), Offline-Abgaben, Service-Worker-Registrierung |
| `app/pwa.py`, `app/templates/pwa/` | Web-Manifest, Service Worker (`/sw.js`), Offline-Seiten, Startbilder |
| `app/context_processors.py` | `nav_section` markiert den aktiven Menüpunkt; Zähler für Glocke und Reiter „Üben“ |
| `app/templates/_*.html` | Wiederverwendbare Teile, z.&nbsp;B. `_practice_menu.html` (Menü „Üben“), `_question_tools.html` (Merken/Melden), `_learning_bar.html` |

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
| Quiz | `label.answer-option` (enthält Checkbox/Radio; Zustand über `:has(:checked)`) > `span.answer-letter` |
| Rückmeldung | `spinner`, `btn.is-loading` (setzt `app.js` automatisch beim Absenden), `page-progress` (Ladebalken), `toast-stack` > `toast` + `toast-info/success/warning/error`, `count-badge` (Zähler) |
| Rechtstexte | `legal` (Fließtext mit Überschriften/Listen), `legal-check` (Hinweis „rechtlich prüfen“) |

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

Sicherheitsabfragen bleiben `onclick="return confirm('…')"` bzw. `onsubmit="return confirm('…')"`.

Formulare und Links bekommen Ladebalken und Spinner automatisch (`pageFeedback` in `app.js`); ausnehmen mit `data-no-progress`. Meldungen aus Views (`django.contrib.messages`) erscheinen als Hinweise unten; aus JavaScript mit `window.toast('Text', { level: 'success' })`.

## Regeln

- Mobile first: alles muss ab 360 px Breite bedienbar sein, Touch-Ziele mindestens 44 px (`btn` erfüllt das).
- Breite Tabellen immer in `table-wrap` (horizontal scrollbar).
- Keine Inline-Styles außer für dynamische Werte (z. B. `style="width: {{ pct }}%"`).
- Seitentitel über `{% block page_title %}…{% endblock %}`.
- Aktuelle Seite in Navigationen mit `aria-current="page"` markieren, nicht nur farbig.
- Text in `text-ink-3` hat mindestens 4,5:1 Kontrast (hell und dunkel); keine helleren Grautöne für Text verwenden.
- Mehrzeilige Template-Kommentare mit `{% comment %}…{% endcomment %}` – `{# … #}` gilt nur für eine Zeile und erscheint sonst als Text auf der Seite.
- Keine externen Skripte, Schriften oder Bilder (Content-Security-Policy); alles lokal ablegen.
