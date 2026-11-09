# Entwicklung

Lokale Einrichtung, tägliche Arbeit und Konventionen. Architektur-Überblick: [Architektur](architektur.md).

## Voraussetzungen

- **Python 3.13** (Django 6.0 braucht mindestens 3.12; das Projekt wird mit 3.13 entwickelt)
- **Git**
- Internetzugang beim ersten Tailwind-Aufruf (lädt die Tailwind-Binary nach `.django_tailwind_cli/`)
- Kein Node.js, keine Datenbank-Installation nötig (lokal SQLite)

Optional: Zugangsdaten für Divera und Microsoft Entra, wenn diese Anmeldewege lokal getestet werden sollen. Ohne sie funktioniert die Anmeldung mit lokalen Konten.

## Einrichten

Ordnerstruktur wie beim Hauptentwickler: das Repository liegt in `la_tool/`, das virtuelle Environment daneben.

```bash
git clone https://github.com/luca-alexander-thomas/LA-Tool.git la_tool
python -m venv venv
venv\Scripts\activate                # Linux/macOS: source venv/bin/activate
cd la_tool
pip install -r requirements.txt
copy .env.example .env               # Linux/macOS: cp .env.example .env
```

In der `.env` (liegt neben `manage.py`) für die Entwicklung mindestens:

```ini
DEBUG=True
SECRET_KEY=irgendein-langer-zufallswert
```

Mit `DEBUG=True` darf `SECRET_KEY` fehlen (dann gilt ein fester Entwicklungsschlüssel), alle Hostnamen sind erlaubt und Cookies funktionieren ohne HTTPS. Alle Variablen: [Konfiguration](referenz/konfiguration.md).

## Datenbank

Migrationsdateien sind derzeit **nicht im Repository** und werden lokal erzeugt (die Umstellung auf versionierte Migrationen ist beschlossen, [Entscheidung 0001](entscheidungen/0001-deployment-strategie.md#schritt-2-migrationen-versionieren-einmalig); danach entfällt `makemigrations` hier und neue Migrationen werden mit committet):

```bash
python manage.py makemigrations app la_tool_admin
python manage.py migrate
python manage.py createsuperuser
```

Nach jeder Modelländerung erneut `makemigrations` und `migrate` ausführen. Die Stufen Bronze, Silber, Gold und Inhalte legt man im Admin-Bereich an (`/admin/`) oder importiert Fragen unter Admin → Fragen-Import (XLSX/CSV/JSON; Beispieldateien dort zum Herunterladen).

Eine andere Datenbankdatei (z.&nbsp;B. eine Kopie zum Testen) wählt `DB_SQLITE_FILE`:

```bash
DB_SQLITE_FILE=kopie.sqlite3 python manage.py runserver     # PowerShell: $env:DB_SQLITE_FILE='kopie.sqlite3'
```

## Starten

```bash
python manage.py tailwind runserver
```

Startet Django auf <http://127.0.0.1:8000> und baut das Stylesheet bei Änderungen an Templates oder `tailwind/source.css` neu. Alternativ ohne Watcher: `python manage.py runserver`.

| Adresse | Inhalt |
|---|---|
| `/` | App (Login unter `/login/`) |
| `/admin/` | Eigener Admin-Bereich (braucht Recht „Admin-Bereich zugreifen“; Superuser haben alle Rechte) |
| `/django-admin/` | Django-Admin, **nur mit `DEBUG=True`** |
| `/healthz/` | Health-Check |

**Testen auf dem Smartphone:** Die PWA (Service Worker, Push) braucht HTTPS. Für Tests von außen eignen sich Tunnel wie VS Code Dev Tunnels; mit `DEBUG=True` sind alle Hostnamen erlaubt.

## Stylesheet bauen

```bash
python manage.py tailwind build
```

Erzeugt `assets/css/tailwind.css`. Die Datei ist **eingecheckt** und muss nach Änderungen an Templates (neue Klassen) oder `tailwind/source.css` neu gebaut und mit committet werden. Tailwind scannt die Templates und `la_tool_admin/forms.py` (siehe `@source` in `tailwind/source.css`).

## Tests

```bash
python manage.py test
```

Läuft in einer temporären Testdatenbank (ca. 40 s, Stand: 136 Tests). Einzelne Bereiche:

```bash
python manage.py test app.tests_learning
python manage.py test la_tool_admin.tests.AdminQueryCountTests
```

| Datei | Schwerpunkt |
|---|---|
| `app/tests.py` | Training, Prüfung, Nachschlagen, Gruppenaufgaben, Grundfunktionen |
| `app/tests_learning.py` | Lernkartei, „Heute lernen“, Merken/Melden, Lernstand, Erinnerungen, Lernaufträge |
| `app/tests_pwa.py` | Benachrichtigungen, Offline-Abgabe, Offline-Daten, „Angemeldet bleiben“ |
| `app/tests_security.py` | Login-Drosselung, Entra-Zuordnung, Prüfungs-Integrität, Header, Health-Check |
| `app/tests_privacy.py` | Divera-Key, Entra-Pflicht, PKCE, Datenexport, Löschkonzept, Rechtstexte |
| `la_tool_admin/tests.py` | Rechte im Admin-Bereich, Push, Abfragezahl der Listen |
| `la_tool_admin/tests_idp.py` | Divera-Login, Gruppenabgleich, `sync_divera_users`, Admin-Filter |

Externe Dienste (Divera, Graph, Web Push) werden in Tests gemockt. Es gibt **keine** JavaScript-Tests und keinen Linter; eine CI (GitHub Actions) ist beschlossen, aber noch nicht eingerichtet. Oberflächenänderungen im Browser prüfen.

Vor einem Commit mindestens:

```bash
python manage.py check
python manage.py makemigrations --check --dry-run    # keine vergessenen Modelländerungen
python manage.py test
```

## Arbeitsweise und Konventionen

- **Sprache:** Oberfläche, Kommentare, Docstrings und Commit-Nachrichten auf Deutsch.
- **Commits:** kurze Betreffzeile, darunter Stichpunkte zum Was und Warum. Keine `.env`, Datenbanken, Migrationen oder `media/` committen.
- **Code-Stil:** an den umgebenden Code anpassen; Kommentare erklären das *Warum*. Ergänzende Funktionen dort ablegen, wo die Verantwortung liegt (Lernlogik in `learning.py`, Bewertung in `scoring.py`, Divera in `login_function.py`).
- **Inhalte nur freigegeben ausliefern:** neue Nutzer-Views filtern über `_published()` bzw. `learning.published_theory()`.
- **Admin-Views** immer mit `@admin_permission_required('app.<recht>')` (oder `@admin_required`) dekorieren; neue Rechte in `SiteSettings.Meta.permissions` und `APP_PERMISSIONS` (`la_tool_admin/views.py`) ergänzen.
- **Formulare und Aktionen:** zustandsändernde Aktionen nur per POST mit CSRF-Token; Rückmeldung über `messages` (erscheint als Hinweis unten).
- **JavaScript:** Alpine-Komponenten in `app/static/js/app.js` registrieren; JSON für Templates mit `json_script` übergeben, Werte in JS-Strings mit `escapejs`.
- **Externe Skripte** sind per Content-Security-Policy gesperrt; Bibliotheken lokal unter `app/static/vendor/` ablegen.
- **Oberfläche:** Komponenten-Klassen und Regeln im [Design-System](design-system.md).

## Fehlersuche

- Mit `DEBUG=True` zeigt Django Fehlerseiten mit Traceback; App-Meldungen (Divera, Push, Login) erscheinen im Terminal (Logger `app` und `la_tool_admin`).
- **Änderungen an CSS/JS erscheinen nicht:** Seite hart neu laden (Strg+Shift+R). Der Service Worker lädt statische Dateien bei `DEBUG=True` immer zuerst vom Server, eine vorher installierte ältere Version greift aber erst nach einem Neuladen.
- **`runserver --noreload`** lädt geänderte Templates nicht neu (Template-Cache) – Server neu starten.
- **Abfragen untersuchen:** `django.test.utils.CaptureQueriesContext` (Beispiel in `la_tool_admin/tests.py`, `AdminQueryCountTests`).
- **Interaktive Shell:** `python manage.py shell` (Modelle werden automatisch importiert).
- **Lokal wie Produktion prüfen:**

  ```bash
  DEBUG=False SECRET_KEY=test HOSTNAME=localhost python manage.py check --deploy
  ```
