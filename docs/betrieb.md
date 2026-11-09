# Betrieb und Wartung

Wiederkehrende Aufgaben, Überwachung, Backups und Fehlerdiagnose im Produktivbetrieb. Einrichtung des Servers: [Deployment](deployment.md).

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
User=la-tool
WorkingDirectory=/srv/la-tool/la_tool
ExecStart=/srv/la-tool/venv/bin/python manage.py sync_divera
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

- Gunicorn schreibt Zugriffs- und Fehlerlog nach stdout/stderr (`accesslog = "-"`) → `journalctl -u la-tool.service`.
- Django-Logger `app` und `la_tool_admin` (Level INFO, Format `Zeit Level Logger: Meldung`) landen ebenfalls dort. Protokolliert werden u.&nbsp;a. Divera-Fehler, Push-Fehler, fehlgeschlagene Anmeldungen (mit IP), gesperrte Konten.
- Accesskeys und Tokens werden nicht geloggt (`divera_error_text` lässt URLs weg).
- Es gibt kein externes Fehler-Tracking (z.&nbsp;B. Sentry) und keine E-Mail bei Fehlern (`ADMINS` nicht gesetzt).

```bash
journalctl -u la-tool.service --since "1 hour ago" | grep -E "ERROR|WARNING"
journalctl -u la-tool.service | grep "Fehlgeschlagene Anmeldung"
```

## Monitoring

- **Health-Check:** `GET /healthz/` → `200 {"status": "ok"}`, wenn die Datenbank antwortet, sonst `503`. Ohne Anmeldung, nicht gecacht. Geeignet für Uptime-Monitoring und Proxy-Checks.
- **Timer:** `systemctl list-timers` und der Exit-Status der Dienste (`systemctl status la-tool-*.service`).

## Backup und Wiederherstellung

Zu sichern sind **Datenbank**, **`media/`** (hochgeladene PDFs/Bilder, Stufen-Icons) und die **`.env`** (Geheimnisse, getrennt und geschützt aufbewahren). Die auf dem Server erzeugten **Migrationsdateien** (`app/migrations/`, `la_tool_admin/migrations/`) gehören zum Datenbankstand und sollten mitgesichert werden.

Im Repository ist kein Backup-Skript vorhanden. Beispiel für MySQL:

```bash
STAMP=$(date +%F)
mysqldump --single-transaction -u la_tool -p la_tool | gzip > /backup/la-tool-db-$STAMP.sql.gz
tar czf /backup/la-tool-media-$STAMP.tar.gz -C /srv/la-tool/la_tool media app/migrations la_tool_admin/migrations
```

Wiederherstellen:

```bash
sudo systemctl stop la-tool.service
gunzip -c /backup/la-tool-db-<datum>.sql.gz | mysql -u la_tool -p la_tool
tar xzf /backup/la-tool-media-<datum>.tar.gz -C /srv/la-tool/la_tool
sudo systemctl start la-tool.service
curl -fsS https://la-tool.thw-jugend-ge.de/healthz/
```

Bei SQLite genügt eine Kopie der Datenbankdatei bei gestopptem Dienst. Die Wiederherstellung sollte einmal testweise (z.&nbsp;B. in eine lokale Kopie) geübt werden.

## Wartung

### Abhängigkeiten

Versionen sind in `requirements.txt` fest vorgegeben. Regelmäßig auf bekannte Sicherheitslücken prüfen, z.&nbsp;B. mit `pip-audit` in einem separaten venv:

```bash
python -m venv /tmp/audit && /tmp/audit/bin/pip install pip-audit
/tmp/audit/bin/pip-audit -r requirements.txt
```

Nach Updates: Tests lokal, dann regulärer [Update-Ablauf](deployment.md#update). `cryptography` ist wegen `msal` auf `<51` begrenzt.

### Geheimnisse wechseln

| Geheimnis | Folgen eines Wechsels |
|---|---|
| `SECRET_KEY` | alle Sitzungen ungültig (alle müssen sich neu anmelden), Passwort-Reset-Links ungültig. Der alte Schlüssel stand früher in der Git-Historie → in Produktion einen neuen verwenden |
| `VAPID_*` | alle Push-Abos ungültig; Nutzer müssen Push neu einschalten |
| `DIVERA_ADMIN_USER_API_KEY` | nur in der `.env` tauschen; betrifft `sync_divera` und `sync_divera_users` |
| `AZURE_CLIENT_SECRET` | in Entra neu erzeugen, in der `.env` tauschen, Dienst neu starten |

### Datenbank

- Löschkonzept automatisch über `cleanup_data` (Fristen in `app/legal_info.py`).
- Ungenutzt, aber vorhanden: Modell/Tabelle `Changes` (`la_tool_admin`).
- Stufen-Icons älterer Uploads einmalig verkleinern: `python manage.py optimize_icons`.

### PWA-Bilder

Startbilder (`app/static/pwa/startup/`) und Screenshots für den Installationsdialog (`app/static/pwa/screenshots/`, aus einem Demo-Konto) bei größeren Design-Änderungen neu erzeugen; die Dateinamen stehen in `app/templates/pwa/_startup_images.html` bzw. `SCREENSHOTS` in `app/pwa.py`.

## Fehlerdiagnose

| Symptom | Prüfen |
|---|---|
| `/healthz/` liefert 503 | Datenbank erreichbar? Zugangsdaten in der `.env`? `journalctl` zeigt „Health-Check: Datenbank nicht erreichbar“ |
| Divera-Anmeldung schlägt für alle fehl | Divera erreichbar? Bei Ausfall gilt das lokal gespeicherte Passwort (Hash) als Notfall-Login – außer für Admins mit Microsoft-Konto |
| „Zu viele fehlgeschlagene Anmeldeversuche“ | Sperre 15 Minuten; zählt je Gunicorn-Worker. Neustart des Dienstes leert die Zähler |
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
