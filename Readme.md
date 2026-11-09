# LA-Tool der THW-Jugend Gelsenkirchen

> [!NOTE]
> In aktiver Entwicklung. Produktion: <https://la-tool.thw-jugend-ge.de>

Web-App zur Vorbereitung auf das **Leistungsabzeichen der THW-Jugend** (Bronze, Silber, Gold): Theorie üben mit Lernkartei, Praxis- und Gruppenaufgaben, Übungsprüfungen, Dienste aus Divera 24/7 und ein Admin-Bereich für Betreuer – als installierbare Progressive Web App.

| Bereich | Technik |
|---|---|
| Backend | Python 3.13, Django 6.0 |
| Oberfläche | Django-Templates, Tailwind CSS v4 (`django-tailwind-cli`, ohne Node.js), Alpine.js |
| App | PWA mit Offline-Funktionen und Web Push |
| Anmeldung | Divera 24/7, Microsoft Entra ID, lokal |
| Datenbank | SQLite (Entwicklung), MySQL (Produktion) |
| Betrieb | Gunicorn + WhiteNoise hinter openresty, systemd-Timer; Ziel: Docker Compose ([Entscheidung](docs/entscheidungen/0001-deployment-strategie.md)) |

## Schnellstart (lokal)

```bash
python -m venv venv
venv\Scripts\activate                 # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                # Linux/macOS: cp .env.example .env (enthält DEBUG=True)
python manage.py makemigrations app la_tool_admin   # Migrationen sind nicht im Repository
python manage.py migrate
python manage.py createsuperuser
python manage.py tailwind runserver   # http://127.0.0.1:8000, Admin unter /admin/
```

Tests: `python manage.py test`

Ausführlich: [Entwicklung](docs/entwicklung.md).

## Dokumentation

| Thema | |
|---|---|
| Aufbau, Komponenten, Datenmodell, Anmeldung | [Architektur](docs/architektur.md) |
| Einrichten, Entwickeln, Testen, Konventionen | [Entwicklung](docs/entwicklung.md) · [Design-System](docs/design-system.md) |
| Installation und Updates auf dem Server | [Deployment](docs/deployment.md) · [Übergangsbetrieb](docs/deployment-uebergang.md) |
| Timer, Logs, Backups, Fehlersuche | [Betrieb](docs/betrieb.md) |
| Rechte, Sicherheit, Datenschutz, Löschkonzept | [Sicherheit und Datenschutz](docs/sicherheit-datenschutz.md) |
| Umgebungsvariablen, Befehle, Endpunkte, Modelle | [Referenz](docs/README.md#referenz) |

Übersicht aller Dokumente: [docs/README.md](docs/README.md).

## Mitwirken

Feature-Wünsche und Fehler bitte als GitHub-Issue melden. Hinweise zu Arbeitsweise und Konventionen: [Entwicklung](docs/entwicklung.md#arbeitsweise-und-konventionen).
