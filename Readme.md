# LA Tool der THW-Jugend Gelsenkirchen

> [!WARNING]  
> In Aktiver Entwicklung!

# Beschreibung

Dieses Projekt bietet eine Plattform zum lernen und Abfragen von Theorie und Praxis Aufgaben für das Leistungsabzeichen der THW-Jugend angepasst auf die THW-Jugend Gelsenkirchen

# Technik

| Bereich | Technik |
|---|---|
| Backend | Python 3.13, Django 6 |
| Frontend | Django-Templates, Tailwind CSS v4 (über `django-tailwind-cli`, kein Node.js nötig), Alpine.js |
| App | Progressive Web App: installierbar, Offline-Hinweisseite |
| Anmeldung | Lokal, DIVERA 24/7, Microsoft Entra ID |
| Datenbank | SQLite (Entwicklung), MySQL (Produktion) |

Das Design-System (Farben, Komponenten-Klassen, Muster) ist in [DESIGN.md](DESIGN.md) beschrieben.

# Lokale Entwicklung

```bash
python -m venv venv
venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env           # Linux/macOS: cp .env.example .env – Werte eintragen
python manage.py makemigrations app la_tool_admin   # Migrationsdateien sind (noch) nicht im Repository
python manage.py migrate
python manage.py createsuperuser
python manage.py tailwind runserver
```

`tailwind runserver` startet Django und baut das Stylesheet bei Template-Änderungen automatisch neu.
Beim ersten Aufruf wird die Tailwind-Binary nach `.django_tailwind_cli/` geladen.

# Deployment

Nach jedem Update auf dem Server:

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py tailwind build    # Stylesheet bauen (assets/css/tailwind.css)
python manage.py collectstatic --noinput
sudo systemctl restart <gunicorn-dienst>
```

Für die PWA muss die Seite über HTTPS laufen. Der Service Worker liegt unter `/sw.js` und wird von Django ausgeliefert.

## Dienste automatisch aus DIVERA abgleichen

`python manage.py sync_divera` legt Dienste aus DIVERA an bzw. aktualisiert sie (dasselbe wie der Button im Admin-Bereich).
Für einen regelmäßigen Abgleich einen systemd-Timer einrichten (Pfade und Benutzer anpassen):

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

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now la-tool-sync.timer
journalctl -u la-tool-sync.service -n 20
```

In DIVERA gelöschte Termine werden beim Abgleich nicht entfernt.

# Mitwirken

Im aktuellen Entwicklungsstadium können über GitHub Issues Feature Requests eingereicht werden.
