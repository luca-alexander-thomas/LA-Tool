# Lizenzhinweise

LA-Tool – Vorbereitung auf das Leistungsabzeichen der THW-Jugend
Copyright (C) 2026 Luca-Alexander Thomas

Dieses Programm ist freie Software: Sie können es unter den Bedingungen der GNU Affero General Public License,
Version 3, wie von der Free Software Foundation veröffentlicht, weitergeben und/oder ändern (siehe [LICENSE](LICENSE)).
Es wird ohne jede Gewährleistung bereitgestellt.

Wer eine geänderte Fassung als Webdienst betreibt, muss den Nutzern den Quellcode dieser Fassung anbieten
(AGPL-3.0, Abschnitt 13). Die Anwendung verlinkt dazu auf der Seite „Lizenzen“ (`/lizenzen/`) das Repository.

## Ausgenommen: Marken, Logos und Abzeichen

Nicht unter der AGPL stehen die Logos, Abzeichen und Kennzeichen der Bundesanstalt Technisches Hilfswerk (THW)
und der THW-Jugend, insbesondere:

- `app/static/img/` (Logo der THW-Jugend Gelsenkirchen, Abzeichen Bronze/Silber/Gold, THW-Dienststellungskennzeichen)
- `app/static/pwa/` (App-Icons, Startbilder und Screenshots, abgeleitet vom Logo)

Die Rechte daran liegen bei den jeweiligen Inhabern. Wer das Programm für eine andere Organisation einsetzt,
muss diese Dateien durch eigene ersetzen.

Ebenfalls nicht Teil der Lizenz sind die Inhalte der Fragenkataloge; sie stammen aus den Unterlagen der THW-Jugend
zum Leistungsabzeichen und werden über die Datenbank verwaltet.

## Verwendete Fremdkomponenten

Im Repository enthalten (Lizenztext jeweils im Dateikopf bzw. bei der Quelle):

| Komponente | Version | Lizenz | Ort |
|---|---|---|---|
| [Alpine.js](https://alpinejs.dev) | 3.14.9 | MIT | `app/static/vendor/alpine.min.js` |
| [PDF.js](https://mozilla.github.io/pdf.js/) | 3.11.174 | Apache-2.0 | `app/static/vendor/pdfjs/` |
| [Heroicons](https://heroicons.com) | 2.2.0 | MIT | `app/templates/icons/` |
| [Tailwind CSS](https://tailwindcss.com) | 4 (nur Build) | MIT | erzeugt `assets/css/tailwind.css` |

Python-Pakete (`requirements.txt`, `requirements-prod.txt`):

| Paket | Version | Lizenz |
|---|---|---|
| Django | 6.0.10 | BSD-3-Clause |
| django-tailwind-cli | 4.8.2 | MIT |
| msal | 1.39.0 | MIT |
| openpyxl | 3.1.5 | MIT |
| Pillow | 13.0.0 | MIT-CMU |
| pywebpush | 2.4.0 | MPL-2.0 |
| cryptography | 50.x | Apache-2.0 OR BSD-3-Clause |
| python-dotenv | 1.2.2 | BSD-3-Clause |
| requests | 2.34.2 | Apache-2.0 |
| WhiteNoise | 6.9.0 | MIT |
| Gunicorn (Produktion) | 27.0.0 | MIT |
| mysqlclient (Produktion) | 2.3.1 | GPL-2.0-or-later |

Die Liste spiegelt den Stand der Abhängigkeiten beim Erstellen dieser Datei; bei Updates bitte mitpflegen
(ebenso `app/templates/legal-lizenzen.html`).
