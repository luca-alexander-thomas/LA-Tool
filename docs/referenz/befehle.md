# Befehle

Projekteigene Management-Befehle (`app/management/commands/`) und die im Projekt genutzten Django-/Tailwind-Befehle. Aufruf jeweils im Verzeichnis mit `manage.py` und aktiviertem venv. Zeitpläne für den Betrieb: [Betrieb](../betrieb.md#wiederkehrende-aufgaben-timer).

## Projekteigene Befehle

| Befehl | Optionen | Wirkung | Voraussetzung |
|---|---|---|---|
| `sync_divera` | – | Holt Termine des Standorts mit dem Admin-Key, filtert auf `DIVERA_EVENTS_GROUP` (Termine ohne Gruppe immer) und legt Dienste an bzw. aktualisiert Titel, Zeit, Ort und Beschreibung (Schlüssel: `Work.divera_id`). Gleiche Funktion wie Admin → Dienste → Abgleich | `DIVERA_ADMIN_USER_API_KEY` |
| `sync_divera_users` | `--dry-run` | Gleicht alle Konten mit Divera-ID gegen die Personenliste ab: Qualifikationen und Gruppen aktualisieren, Gruppen neu berechnen, Ausgetretene sperren (nur Divera-Konten, die schon gelistet waren). Bricht bei leerer Liste ohne Änderungen ab | `DIVERA_ADMIN_USER_API_KEY` |
| `send_learning_reminders` | `--dry-run` | Push „Zeit für eine Wiederholung“ mit Knopf „Jetzt üben“ an Personen mit Push-Gerät, eingeschalteter Lern-Erinnerung und fälligen Fragen; je Person höchstens alle 6 Tage | `VAPID_*` (bei `--dry-run` nicht) |
| `cleanup_data` | `--dry-run` | Löschkonzept: löscht abgelaufene Trainings, Prüfungsergebnisse, Benachrichtigungen, erledigte Meldungen und Konten ausgetretener Mitglieder (Fristen: `RETENTION` in `app/legal_info.py`) | – |
| `generate_vapid_keys` | – | Gibt ein neues VAPID-Schlüsselpaar für die `.env` aus. Neue Schlüssel machen bestehende Push-Abos ungültig | – |
| `optimize_icons` | – | Verkleinert vorhandene Stufen-Icons auf max. 160 px und speichert sie als WebP (neue Uploads automatisch) | – |

## Django-Befehle im Projekt

| Befehl | Wann |
|---|---|
| `makemigrations app la_tool_admin` | nach Modelländerungen und bei jedem Deployment (Migrationen sind nicht versioniert) |
| `migrate` / `migrate --plan` | Datenbank aktualisieren / Plan vorher ansehen |
| `createsuperuser` | erster Admin bzw. Notfall-Admin ohne Microsoft-Verknüpfung |
| `collectstatic --noinput` | bei jedem Deployment (WhiteNoise-Manifest) |
| `check` / `check --deploy` | Konfiguration prüfen / mit Produktionswerten |
| `test` | Testsuite, siehe [Entwicklung](../entwicklung.md#tests) |
| `clearsessions` | abgelaufene Sitzungen löschen (täglich) |
| `shell` | interaktive Shell mit automatisch importierten Modellen |

## Tailwind (`django-tailwind-cli`)

| Befehl | Wirkung |
|---|---|
| `tailwind runserver` | Entwicklungsserver mit automatischem Neubau des Stylesheets |
| `tailwind build` | baut `assets/css/tailwind.css` (vor jedem Commit mit Template-Änderungen und bei jedem Deployment) |
| `tailwind watch` | nur Watcher, ohne Server |
| `tailwind download_cli` | Tailwind-Binary nach `.django_tailwind_cli/` laden (passiert sonst beim ersten Aufruf) |
