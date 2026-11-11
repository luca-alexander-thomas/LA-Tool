# Betrieb und Wartung

Wiederkehrende Aufgaben, Überwachung, Backups und Fehlerdiagnose im Produktivbetrieb. Einrichtung des Servers: [Deployment](deployment.md).

## Befehle aufrufen

Management-Befehle (`manage.py …`) laufen je nach Umgebung unterschiedlich. Überall in diesem Dokument steht nur der Befehl; davor gehört:

| Umgebung | Aufruf |
|---|---|
| Produktion | `cd /home/compose/la-tool && docker compose exec app python manage.py <befehl>` |
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

Die Timer liegen im Repository unter `deploy/systemd/`; `deploy/deploy.sh` spielt sie bei jedem Deployment nach `/etc/systemd/system/` ein und aktiviert sie. Eine Vorlage `la-tool-task@.service` führt `docker compose exec -T app python manage.py %i` aus; je Befehl gibt es einen Timer:

| Timer | Zeitplan | Befehl |
|---|---|---|
| `la-tool-sync-divera.timer` | stündlich 06–22 Uhr (:05) | `sync_divera` |
| `la-tool-sync-divera-users.timer` | täglich 03:15 | `sync_divera_users` |
| `la-tool-cleanup-data.timer` | täglich 03:45 | `cleanup_data` |
| `la-tool-clearsessions.timer` | täglich 04:00 | `clearsessions` |
| `la-tool-learning-reminders.timer` | So 18:00 | `send_learning_reminders` |
| `la-tool-backup.timer` | täglich 02:30 | `deploy/backup.sh` |

Zeitpläne nur im Repository ändern (sonst überschreibt das nächste Deployment sie).

```bash
systemctl list-timers 'la-tool-*'
systemctl start la-tool-task@cleanup_data.service       # sofort ausführen
journalctl -u la-tool-task@sync_divera.service -n 20
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

- Gunicorn schreibt Zugriffs- und Fehlerlog nach stdout/stderr (`accesslog = "-"`). Docker speichert die Logs rotierend (3 × 10 MB): `docker compose logs app`.
- Django-Logger `app` und `la_tool_admin` (Level INFO, Format `Zeit Level Logger: Meldung`) landen ebenfalls dort. Protokolliert werden u.&nbsp;a. Divera-Fehler, Push-Fehler, fehlgeschlagene Anmeldungen (mit IP), gesperrte Konten.
- Accesskeys und Tokens werden nicht geloggt (`divera_error_text` lässt URLs weg).
- Es gibt kein externes Fehler-Tracking (z.&nbsp;B. Sentry) und keine E-Mail bei Fehlern (`ADMINS` nicht gesetzt).

```bash
docker compose logs --since 1h app | grep -E "ERROR|WARNING"
docker compose logs app | grep "Fehlgeschlagene Anmeldung"
```

## Monitoring

- **Health-Check:** `GET /healthz/` → `200 {"status": "ok"}`, wenn die Datenbank antwortet, sonst `503`. Ohne Anmeldung, nicht gecacht. Geeignet für Uptime-Monitoring und Proxy-Checks.
- **Container:** `docker compose ps` zeigt den Healthcheck-Status von `app` und `db`; Docker startet abgestürzte Container neu (`restart: unless-stopped`).
- **Extern:** ein Uptime-Dienst ruft `https://la-tool.thw-jugend-ge.de/healthz/` alle paar Minuten ab und benachrichtigt bei Ausfall (Dienst noch festzulegen, bevorzugt EU-Anbieter oder selbst gehostet).
- **Timer:** `systemctl list-timers 'la-tool*'`; bei Fehlschlag benachrichtigen, z.&nbsp;B. über `OnFailure=` an einen Mail- oder Ping-Dienst. Besonders das Backup muss überwacht sein – ein stilles Scheitern fällt sonst erst im Notfall auf.
- **Fehler-Tracking** (optional): Sentry (EU-Region) oder selbst gehostetes GlitchTip.

## Backup und Wiederherstellung

Zu sichern sind **Datenbank**, **`media/`** (Uploads, Stufen-Icons) und die **`.env`**. Migrationen und `compose.yaml` liegen im Repository.

**Ist-Stand:** `deploy/backup.sh` schreibt täglich (Timer 02:30) und vor jedem Deployment einen Dump (`backups/db-<zeit>.sql.gz`) und ein Archiv von `media/` nach `/home/compose/la-tool/backups/` (`700`, nur root). Dateien älter als 14 Tage werden gelöscht.

> **Offen:** Diese Sicherungen liegen auf demselben Server. Gegen Ausfall oder Verlust des Servers hilft nur eine **Offsite-Kopie** (Ziel, siehe [Entscheidung 0001](entscheidungen/0001-deployment-strategie.md)): `backups/` und `.env` mit **restic** verschlüsselt in einen EU-Speicher, Aufbewahrung 7 tägliche, 4 wöchentliche, 6 monatliche Stände, Fehlschlag an die Überwachung melden. Das restic-Passwort zusätzlich offline aufbewahren.

**Wiederherstellen** (im Projektverzeichnis):

```bash
docker compose stop app
gunzip -c backups/db-<zeit>.sql.gz | docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysql -u "$MYSQL_USER" "$MYSQL_DATABASE"'
tar -xzf backups/media-<zeit>.tar.gz          # stellt media/ wieder her
docker compose start app
curl -fsS https://la-tool.thw-jugend-ge.de/healthz/
```

**Wiederherstellung auf einem neuen Server:** Docker installieren, Repository klonen ([Erstinstallation](deployment.md#erstinstallation)), `.env` aus dem Backup zurückholen, `docker compose up -d --wait db`, Dump einspielen, `media/` zurückkopieren, `bash deploy/deploy.sh`.

Die Wiederherstellung einmal im Quartal üben. Gelöschte Daten (Löschkonzept) sind erst nach Ablauf der Backup-Aufbewahrung auch aus den Backups verschwunden.

## Wartung

### Abhängigkeiten

Versionen sind in `requirements.txt` fest vorgegeben. Regelmäßig auf bekannte Sicherheitslücken prüfen, z.&nbsp;B. mit `pip-audit` in einem separaten venv:

```bash
python -m venv /tmp/audit && /tmp/audit/bin/pip install pip-audit
/tmp/audit/bin/pip-audit -r requirements.txt
```

Nach Updates: Tests lokal und in der CI, dann regulärer [Release-Prozess](deployment.md#release-prozess). `cryptography` ist wegen `msal` auf `<51` begrenzt. Ziel: Dependabot meldet Updates für `requirements.txt`, Dockerfile und GitHub Actions; das Image wird mindestens monatlich neu gebaut, damit Sicherheitsupdates des Basis-Images ankommen.

### Geheimnisse wechseln

| Geheimnis | Folgen eines Wechsels |
|---|---|
| `SECRET_KEY` | alle Sitzungen ungültig (alle müssen sich neu anmelden), Passwort-Reset-Links ungültig. Der alte Schlüssel stand früher in der Git-Historie → in Produktion einen neuen verwenden |
| `VAPID_*` | alle Push-Abos ungültig; Nutzer müssen Push neu einschalten |
| `DIVERA_ADMIN_USER_API_KEY` | nur in der `.env` tauschen; betrifft `sync_divera` und `sync_divera_users` |
| `AZURE_CLIENT_SECRET` | in Entra neu erzeugen, in der `.env` tauschen, `app` neu starten |
| Datenbank-Passwort | im laufenden MySQL per `ALTER USER` setzen, dann in der `.env` ändern und `app` neu starten (die `MYSQL_*`-Werte wirken nur beim ersten Start des Volumes) |

### Datenbank

- Löschkonzept automatisch über `cleanup_data` (Fristen in `app/legal_info.py`).
- Ungenutzt, aber vorhanden: Modell/Tabelle `Changes` (`la_tool_admin`).
- Stufen-Icons älterer Uploads einmalig verkleinern: `python manage.py optimize_icons`.

### PWA-Bilder

Startbilder (`app/static/pwa/startup/`) und Screenshots für den Installationsdialog (`app/static/pwa/screenshots/`, aus einem Demo-Konto) bei größeren Design-Änderungen neu erzeugen; die Dateinamen stehen in `app/templates/pwa/_startup_images.html` bzw. `SCREENSHOTS` in `app/pwa.py`.

## Fehlerdiagnose

| Symptom | Prüfen |
|---|---|
| `/healthz/` liefert 503 | Datenbank erreichbar (`docker compose ps db`)? `DB_MYSQL_*` in der `.env` passend zum Volume? Log zeigt „Health-Check: Datenbank nicht erreichbar“ |
| Seite nicht erreichbar, `/healthz/` ohne Antwort | `docker compose ps`, `docker compose logs app`; Proxy-Ziel `127.0.0.1:8001` |
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
- **`/media/`** ist ohne Anmeldung abrufbar (Aufgaben-PDFs, Bilder, temporäre Uploads unter `media/tmp/`).
- **Offline:** Auf Geräten gespeicherte Theoriefragen bleiben während einer Prüfung lesbar (der Server sperrt nur das Nachladen).
