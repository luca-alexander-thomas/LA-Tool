# Konfiguration

Alle Einstellungen kommen aus der Datei `.env` neben `manage.py` (gelesen von `la_tool/env.py` mit `python-dotenv`). Vorlage: [`.env.example`](../../.env.example). Wo die Werte wirken: `la_tool/settings.py`.

> `python-dotenv` überschreibt **keine** bereits gesetzten Umgebungsvariablen. Ist z.&nbsp;B. `HOSTNAME` in der Shell oder im systemd-Dienst schon gesetzt, gilt dieser Wert statt der `.env`.

Wahrheitswerte: `1`, `true`, `yes`, `on` (ohne Groß/klein) gelten als wahr, alles andere als falsch.

## Django und HTTP

| Variable | Standard | Pflicht | Bedeutung |
|---|---|---|---|
| `DEBUG` | `False` | – | Entwicklungsmodus: Fehlerseiten mit Traceback, alle Hostnamen erlaubt, Cookies ohne HTTPS, `/django-admin/`, `/media/` über Django. In Produktion nie aktivieren |
| `SECRET_KEY` | – | in Produktion | Signiert Sitzungen und Tokens. Fehlt er bei `DEBUG=False`, startet Django nicht; mit `DEBUG=True` gilt ein fester Entwicklungsschlüssel |
| `HOSTNAME` | `localhost` | in Produktion | Erlaubter Hostname (`ALLOWED_HOSTS`), z.&nbsp;B. `la-tool.thw-jugend-ge.de` |
| `EXTRA_HOSTS` | leer | – | Weitere Hostnamen, durch Komma getrennt |
| `TRUST_X_FORWARDED_PROTO` | `False` | hinter HTTPS-Proxy | Vertraut `X-Forwarded-Proto: https` des Proxys (`SECURE_PROXY_SSL_HEADER`) und nimmt den letzten `X-Forwarded-For`-Eintrag als Client-IP. Nur einschalten, wenn der Proxy die Header setzt |
| `SECURE_SSL_REDIRECT` | `False` | – | Django leitet HTTP auf HTTPS um. Meist übernimmt das der Proxy; ohne `TRUST_X_FORWARDED_PROTO` droht eine Endlosschleife |

## Datenbank

| Variable | Standard | Bedeutung |
|---|---|---|
| `DATABASE_TYPE` | `sqlite3` | `sqlite3` oder `mysql` |
| `DB_SQLITE_FILE` | `db.sqlite3` | Pfad der SQLite-Datei, relativ zu `la_tool/` oder absolut |
| `DB_MYSQL_HOST` | `localhost` | MySQL-Server |
| `DB_MYSQL_PORT` | `3306` | Port |
| `DB_MYSQL_USER` | leer | Benutzer |
| `DB_MYSQL_PASSWORD` | leer | Passwort |
| `DB_MYSQL_NAME` | leer | Datenbankname |

MySQL nutzt `CONN_MAX_AGE=60` (Verbindung je Worker wiederverwenden) mit Health-Checks. Treiber `mysqlclient` separat installieren (`pip install "mysqlclient>=2.2.0"`).

## Microsoft Entra ID

| Variable | Standard | Bedeutung |
|---|---|---|
| `AZURE_CLIENT_ID` | leer | Anwendungs-ID der App-Registrierung |
| `AZURE_CLIENT_SECRET` | leer | Client-Geheimnis |
| `AZURE_TENANT_ID` | leer | Tenant-GUID. Mit einer GUID werden Konten anderer Tenants abgelehnt; `common`/`organizations` schalten diese Prüfung ab |
| `AZURE_REDIRECT_URI` | `http://localhost:8000/microsoft-callback/` | Muss exakt in der App-Registrierung eingetragen sein |
| `AZURE_GROUP_ADMINS_ID` | leer | Entra-Gruppe → Django-Gruppe „LA-Tool-Admins“ |
| `AZURE_GROUP_USERS_ID` | leer | Entra-Gruppe → Django-Gruppe „LA-Tool-Benutzer“ |

Benötigte delegierte Berechtigung: `User.Read`.

## Divera 24/7

| Variable | Standard | Bedeutung |
|---|---|---|
| `DIVERA_ADMIN_USER_API_KEY` | leer | Accesskey eines Divera-Kontos mit Zugriff auf Personenliste und Termine des Standorts; nötig für `sync_divera` und `sync_divera_users` |
| `DIVERA_SITE_ID` | `20369` | Standort (Cluster-ID) der THW-Jugend Gelsenkirchen; Anmeldungen anderer Standorte werden abgelehnt |
| `DIVERA_EVENTS_GROUP` | `Jugendliche` | Name der Divera-Gruppe, deren Termine als Dienste importiert werden (Termine ohne Gruppe werden immer importiert) |

## Web Push

| Variable | Standard | Bedeutung |
|---|---|---|
| `VAPID_PUBLIC_KEY` | leer | Öffentlicher Schlüssel (erzeugen mit `python manage.py generate_vapid_keys`) |
| `VAPID_PRIVATE_KEY` | leer | Privater Schlüssel – nie ins Repository |
| `VAPID_SUBJECT` | leer | Kontakt für Push-Dienste, `mailto:…` oder `https://…` |

Fehlt einer der drei Werte, ist Push abgeschaltet; Benachrichtigungen erscheinen trotzdem in der App (Glocke).

## Feste Einstellungen im Code

Nicht über die `.env` änderbar, aber für Betrieb und Fehlersuche relevant:

| Einstellung | Wert | Ort |
|---|---|---|
| Zeitzone, Sprache | `Europe/Berlin`, `de-de` | `settings.py` |
| Sitzungsdauer | 90 Tage mit „Angemeldet bleiben“, täglich verlängert | `settings.py`, `app/middleware.py` |
| Statische Dateien | `STATIC_ROOT=staticfiles/`, WhiteNoise mit Manifest (in Tests ohne) | `settings.py` |
| Uploads | `MEDIA_ROOT=media/`, `MEDIA_URL=/media/` | `settings.py` |
| Cache | Django-Standard (LocMem, je Prozess) | – |
| Logging | Logger `app`, `la_tool_admin` → Konsole, Level INFO | `settings.py` |
| Tailwind | Quelle `tailwind/source.css` → `assets/css/tailwind.css`, CLI 4.1.18 | `settings.py` |
| Aufbewahrungsfristen | `RETENTION` | `app/legal_info.py` |
| Lernkartei, Schwellen | `INTERVALS`, `MASTERED`, `WEAK`, `RECENT` | `app/learning.py` |
| Login-Drosselung | 5 je Name, 30 je IP, 15 Minuten | `app/login_function.py` |
| Prüfungs-Kulanz | 30 s nach Zeitablauf | `EXAM_SUBMIT_GRACE_SEC` in `app/views.py` |
| Fragen-Import | max. 5 MB, 2000 Zeilen | `la_tool_admin/views.py` |
| Push | max. 10 Geräte je Person, erlaubte Push-Hosts | `la_tool_admin/push.py` |
