# Betrieb und Wartung

Wiederkehrende Aufgaben, Überwachung, Backups und Fehlerdiagnose im Produktivbetrieb. Einrichtung des Servers: [Deployment](deployment.md).

## Befehle aufrufen

Management-Befehle (`manage.py …`) laufen je nach Umgebung unterschiedlich. Überall in diesem Dokument steht nur der Befehl; davor gehört:

| Umgebung | Aufruf |
|---|---|
| Zielarchitektur (Compose) | `docker compose -f /srv/la-tool/compose.yaml run --rm app python manage.py <befehl>` |
| [Übergangsbetrieb](deployment-uebergang.md) | `cd /srv/la-tool/la_tool && ../venv/bin/python manage.py <befehl>` |
| Entwicklung | `python manage.py <befehl>` im aktivierten venv |

## Wiederkehrende Aufgaben (Timer)

Alle Aufgaben sind Management-Befehle (Details: [Befehle](referenz/befehle.md)). Neue Befehle zuerst mit `--dry-run` ausführen, sofern vorhanden.

| Befehl | Empfohlener Zeitplan | Aufgabe |
|---|---|---|
| `sync_divera` | stündlich 06–22 Uhr | Dienste der Divera-Gruppe `DIVERA_EVENTS_GROUP` anlegen/aktualisieren |
| `sync_divera_users` | nachts | Qualifikationen/Gruppen aller Divera-verknüpften Konten auffrischen, Ausgetretene sperren |
| `cleanup_data` | täglich | Daten nach Ablauf der Fristen löschen (Löschkonzept) |
| `clearsessions` | täglich | abgelaufene Sitzungen aus der Datenbank entfernen (Django-Befehl) |
| `send_learning_reminders` | wöchentlich, z.&nbsp;B. So 18 Uhr | Push-Erinnerung an fällige Wiederholungen (je Person höchstens alle 6 Tage) |

Beispiel für einen Timer (Pfade und Benutzer anpassen). Für jeden Befehl ein Paar aus `.service` und `.timer`:

`/etc/systemd/system/la-tool-sync.service`

```ini
[Unit]
Description=LA-Tool: Dienste aus DIVERA abgleichen
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/srv/la-tool
ExecStart=/usr/bin/docker compose -f /srv/la-tool/compose.yaml run --rm app python manage.py sync_divera
```

`/etc/systemd/system/la-tool-sync.timer`

```ini
[Unit]
Description=LA-Tool: Dienste-Abgleich stündlich

[Timer]
OnCalendar=*-*-* 06..22:07:00
Persistent=true
RandomizedDelaySec=120

[Install]
WantedBy=timers.target
```

Weitere Zeitpläne: `sync_divera_users` mit `OnCalendar=*-*-* 03:17:00`, `cleanup_data` und `clearsessions` mit `OnCalendar=*-*-* 03:41:00`, `send_learning_reminders` mit `OnCalendar=Sun *-*-* 17:53:00`.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now la-tool-sync.timer
systemctl list-timers 'la-tool*'
journalctl -u la-tool-sync.service -n 20
```

**Hinweise zu `sync_divera_users`:**

- Gesperrt wird nur, wer schon einmal in der Divera-Personenliste stand (`Profile.divera_listed`) und jetzt fehlt. Nach der Erstinstallation bzw. dem Update auf diese Logik sperrt erst der **zweite** Lauf.
- Konten, die nie in der Liste standen (z.&nbsp;B. reine Verwaltungskonten), bleiben unverändert und werden als „nie gelistet“ gemeldet.
- Microsoft-Konten werden nicht gesperrt, erhalten aber Qualifikationen, wenn sie mit Divera verknüpft sind.
- Liefert Divera eine leere Liste, bricht der Befehl ohne Änderungen ab.

## Benachrichtigungen

Jede Nachricht wird als Benachrichtigung in der App gespeichert (Glocke, 90 Tage) und – falls die Person Push auf einem Gerät eingeschaltet hat – als Push zugestellt.

| Auslöser | Empfänger |
|---|---|
| Admin → Prüfung anlegen mit „Push-Benachrichtigung“ | zugewiesene Personen und Gruppen |
| Admin → Ergebnis freigeben mit Benachrichtigung | die geprüfte Person |
| Admin → Lernauftrag anlegen mit „Push-Benachrichtigung“ | Empfänger des Auftrags |
| Admin → Benachrichtigungen (Recht „Benachrichtigungen senden“) | alle aktiven Konten oder gewählte Gruppen; „Test an mich“ prüft die eigenen Geräte |
| `send_learning_reminders` | Personen mit fälligen Fragen und eingeschalteter Lern-Erinnerung |

Push schalten Nutzer je Gerät unter Mein Konto → Benachrichtigungen ein (iPhone/iPad nur in der installierten App).

Bei Prüfung und Ergebnis-Freigabe kann zusätzlich eine private Divera-Nachricht verschickt werden (Option „Divera-Benachrichtigung“, braucht `DIVERA_ADMIN_USER_API_KEY` und eine verknüpfte Divera-ID).

## Logging

- Gunicorn schreibt Zugriffs- und Fehlerlog nach stdout/stderr (`accesslog = "-"`). Mit dem Docker-Logtreiber `journald` landet alles im Journal: `journalctl CONTAINER_NAME=la-tool-app-1` (Übergangsbetrieb: `journalctl -u <gunicorn-dienst>`).
- Django-Logger `app` und `la_tool_admin` (Level INFO, Format `Zeit Level Logger: Meldung`) landen ebenfalls dort. Protokolliert werden u.&nbsp;a. Divera-Fehler, Push-Fehler, fehlgeschlagene Anmeldungen (mit IP), gesperrte Konten.
- Accesskeys und Tokens werden nicht geloggt (`divera_error_text` lässt URLs weg).
- Es gibt kein externes Fehler-Tracking (z.&nbsp;B. Sentry) und keine E-Mail bei Fehlern (`ADMINS` nicht gesetzt).

```bash
journalctl CONTAINER_NAME=la-tool-app-1 --since "1 hour ago" | grep -E "ERROR|WARNING"
journalctl CONTAINER_NAME=la-tool-app-1 | grep "Fehlgeschlagene Anmeldung"
```

## Monitoring

- **Health-Check:** `GET /healthz/` → `200 {"status": "ok"}`, wenn die Datenbank antwortet, sonst `503`. Ohne Anmeldung, nicht gecacht. Geeignet für Uptime-Monitoring und Proxy-Checks.
- **Container:** `docker compose ps` zeigt den Healthcheck-Status von `app` und `db`; Docker startet abgestürzte Container neu (`restart: unless-stopped`).
- **Extern:** ein Uptime-Dienst ruft `https://la-tool.thw-jugend-ge.de/healthz/` alle paar Minuten ab und benachrichtigt bei Ausfall (Dienst noch festzulegen, bevorzugt EU-Anbieter oder selbst gehostet).
- **Timer:** `systemctl list-timers 'la-tool*'`; bei Fehlschlag benachrichtigen, z.&nbsp;B. über `OnFailure=` an einen Mail- oder Ping-Dienst. Besonders das Backup muss überwacht sein – ein stilles Scheitern fällt sonst erst im Notfall auf.
- **Fehler-Tracking** (optional): Sentry (EU-Region) oder selbst gehostetes GlitchTip.

## Backup und Wiederherstellung

Zu sichern sind **Datenbank**, **`media/`** (Uploads, Stufen-Icons) und die Konfiguration (**`.env`**, **`db.env`**, `compose.yaml`). Migrationen sind Teil des Images bzw. Repositorys.

**Verfahren (Ziel, Skript `deploy/backup.sh` aus der Umsetzung):** täglich per systemd-Timer

1. Datenbank-Dump aus dem Container,
2. Dump, `media/` und Konfiguration mit **restic** verschlüsselt in einen EU-Speicher außerhalb des Servers,
3. Aufbewahrung 7 tägliche, 4 wöchentliche, 6 monatliche Stände (`restic forget --prune`),
4. Erfolg oder Fehlschlag an die Überwachung melden.

```bash
# Kern des Backups
docker compose -f /srv/la-tool/compose.yaml exec -T db     sh -c 'mysqldump --single-transaction -u root -p"$MYSQL_ROOT_PASSWORD" la_tool'     > /srv/la-tool/backup/db.sql
restic backup /srv/la-tool/backup /srv/la-tool/media /srv/la-tool/.env /srv/la-tool/db.env /srv/la-tool/compose.yaml
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
```

Das restic-Repository-Passwort liegt auf dem Server (für den Timer) **und** offline bei der verantwortlichen Person – ohne es sind die Backups unbrauchbar.

**Wiederherstellen:**

```bash
restic restore latest --target /tmp/restore
docker compose -f /srv/la-tool/compose.yaml stop app
docker compose -f /srv/la-tool/compose.yaml exec -T db     sh -c 'mysql -u root -p"$MYSQL_ROOT_PASSWORD" la_tool' < /tmp/restore/srv/la-tool/backup/db.sql
rsync -a /tmp/restore/srv/la-tool/media/ /srv/la-tool/media/
docker compose -f /srv/la-tool/compose.yaml start app
curl -fsS https://la-tool.thw-jugend-ge.de/healthz/
```

**Wiederherstellung auf einem neuen Server:** Server vorbereiten ([Deployment](deployment.md#server-vorbereiten-einmalig)), Konfiguration aus dem Backup zurückholen, `docker compose up -d db`, Dump einspielen, `media/` zurückkopieren, `app` mit dem zuletzt genutzten Tag starten.

Die Wiederherstellung einmal im Quartal in Staging oder lokal üben. Gelöschte Daten (Löschkonzept) sind erst nach Ablauf der Backup-Aufbewahrung (max. 6 Monate) auch aus den Backups verschwunden.

**Übergangsbetrieb:** dasselbe Verfahren, nur mit `mysqldump` direkt auf dem Host bzw. einer Kopie der SQLite-Datei bei gestopptem Dienst; die auf dem Server erzeugten Migrationsdateien (`app/migrations/`, `la_tool_admin/migrations/`) mitsichern.

## Wartung

### Abhängigkeiten

Versionen sind in `requirements.txt` fest vorgegeben. Regelmäßig auf bekannte Sicherheitslücken prüfen, z.&nbsp;B. mit `pip-audit` in einem separaten venv:

```bash
python -m venv /tmp/audit && /tmp/audit/bin/pip install pip-audit
/tmp/audit/bin/pip-audit -r requirements.txt
```

Nach Updates: Tests lokal und in der CI, dann regulärer [Update-Ablauf](deployment.md#update). `cryptography` ist wegen `msal` auf `<51` begrenzt. Ziel: Dependabot meldet Updates für `requirements.txt`, Dockerfile und GitHub Actions; das Image wird mindestens monatlich neu gebaut, damit Sicherheitsupdates des Basis-Images ankommen.

### Geheimnisse wechseln

| Geheimnis | Folgen eines Wechsels |
|---|---|
| `SECRET_KEY` | alle Sitzungen ungültig (alle müssen sich neu anmelden), Passwort-Reset-Links ungültig. Der alte Schlüssel stand früher in der Git-Historie → in Produktion einen neuen verwenden |
| `VAPID_*` | alle Push-Abos ungültig; Nutzer müssen Push neu einschalten |
| `DIVERA_ADMIN_USER_API_KEY` | nur in der `.env` tauschen; betrifft `sync_divera` und `sync_divera_users` |
| `AZURE_CLIENT_SECRET` | in Entra neu erzeugen, in der `.env` tauschen, `app` neu starten |
| Datenbank-Passwort | in `db.env` und `.env` gleichzeitig ändern; im laufenden MySQL per `ALTER USER` setzen, dann `app` neu starten |

### Datenbank

- Löschkonzept automatisch über `cleanup_data` (Fristen in `app/legal_info.py`).
- Ungenutzt, aber vorhanden: Modell/Tabelle `Changes` (`la_tool_admin`).
- Stufen-Icons älterer Uploads einmalig verkleinern: `python manage.py optimize_icons`.

### PWA-Bilder

Startbilder (`app/static/pwa/startup/`) und Screenshots für den Installationsdialog (`app/static/pwa/screenshots/`, aus einem Demo-Konto) bei größeren Design-Änderungen neu erzeugen; die Dateinamen stehen in `app/templates/pwa/_startup_images.html` bzw. `SCREENSHOTS` in `app/pwa.py`.

## Fehlerdiagnose

| Symptom | Prüfen |
|---|---|
| `/healthz/` liefert 503 | Datenbank erreichbar (`docker compose ps db`)? Zugangsdaten in `.env`/`db.env` gleich? Log zeigt „Health-Check: Datenbank nicht erreichbar“ |
| Seite nicht erreichbar, `/healthz/` ohne Antwort | `docker compose ps`, `docker compose logs app`; openresty-Upstream `127.0.0.1:8000` |
| Divera-Anmeldung schlägt für alle fehl | Divera erreichbar? Bei Ausfall gilt das lokal gespeicherte Passwort (Hash) als Notfall-Login – außer für Admins mit Microsoft-Konto |
| „Zu viele fehlgeschlagene Anmeldeversuche“ | Sperre 15 Minuten; zählt je Gunicorn-Worker. Neustart von `app` leert die Zähler |
| Admin kann sich nicht mit Passwort anmelden | Admins mit verknüpftem Microsoft-Konto müssen „Mit Microsoft anmelden“ nutzen; Notfall: lokaler Superuser ohne Microsoft-Verknüpfung |
| Microsoft-Login: „gehört nicht zur THW-Jugend Gelsenkirchen“ | `AZURE_TENANT_ID` stimmt nicht oder Konto aus fremdem Tenant/Gastkonto |
| Gruppen fehlen nach Microsoft-Login | Graph `/me/memberOf` fehlgeschlagen (Log „Entra-Gruppen konnten nicht abgerufen werden“) – dann bleiben Gruppen unverändert |
| Push kommt nicht an | `VAPID_*` gesetzt? Admin → Benachrichtigungen → „Test an mich“; iPhone nur in der installierten App |
| Neue Inhalte nicht sichtbar | Entwurf? Frage, Katalog **und** Stufe müssen freigegeben sein |
| Lernstand/Zähler wirkt veraltet | Zahl fälliger Fragen ist bis zu 10 Minuten je Worker gecacht |

## Bekannte Einschränkungen

- **Cache je Worker (LocMem):** Login-Drosselung, Zähler fälliger Fragen (10 min), freigegebene Stufen (60 s) und die globale Fehlerquote (10 min) gelten je Gunicorn-Worker.
- **Divera-Dienste:** `sync_divera` überschreibt bei jedem Lauf Titel, Zeit, Ort und **Beschreibung** importierter Dienste mit den Divera-Werten. Im Admin ergänzte Stufe und Aufgaben bleiben erhalten, eine geänderte Beschreibung nicht. In Divera gelöschte Termine werden nicht entfernt.
- **Gruppenrechte:** Der Admin-Bereich vergibt Einzelrechte an Personen und Gruppenmitgliedschaften, aber **keine Rechte an Gruppen**. Gruppenrechte setzt man über den Django-Admin (`/django-admin/`, nur mit `DEBUG=True`) oder die Shell:

  ```bash
  python manage.py shell -c "from django.contrib.auth.models import Group, Permission; Group.objects.get(name='LA-Tool-Admins').permissions.add(*Permission.objects.filter(content_type__app_label='app', codename__in=['access_admin', 'manage_theory']))"
  ```

- **`/media/`** ist ohne Anmeldung abrufbar (Aufgaben-PDFs, Bilder, temporäre Uploads unter `media/tmp/`).
- **Offline:** Auf Geräten gespeicherte Theoriefragen bleiben während einer Prüfung lesbar (der Server sperrt nur das Nachladen).
