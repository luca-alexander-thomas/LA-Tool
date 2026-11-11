# Dokumentation

Wegweiser durch die Dokumentation des LA-Tools. Kurzüberblick und Schnellstart: [Readme](../Readme.md).

## Nach Aufgabe

| Ich möchte … | Dokument |
|---|---|
| verstehen, wie das System aufgebaut ist | [Architektur](architektur.md) |
| das Projekt lokal einrichten, entwickeln und testen | [Entwicklung](entwicklung.md) |
| Oberflächen bauen (Klassen, Komponenten, Regeln) | [Design-System](design-system.md) |
| die Anwendung auf dem Server installieren oder aktualisieren | [Deployment](deployment.md) |
| Timer, Logs, Backups und Fehlersuche im laufenden Betrieb | [Betrieb](betrieb.md) |
| Rechte vergeben, Sicherheit und Datenschutz verstehen | [Sicherheit und Datenschutz](sicherheit-datenschutz.md) |

## Referenz

Nachschlagetabellen, die bei Code-Änderungen mitgepflegt werden müssen:

| Referenz | Inhalt | Quelle im Code |
|---|---|---|
| [Konfiguration](referenz/konfiguration.md) | Umgebungsvariablen (`.env`) und feste Einstellungen | `la_tool/env.py`, `la_tool/settings.py` |
| [Befehle](referenz/befehle.md) | Management-Befehle | `app/management/commands/` |
| [Endpunkte](referenz/urls.md) | Routen, JSON-Endpunkte, Rechte im Admin-Bereich | `app/urls.py`, `la_tool_admin/urls.py` |
| [Datenmodell](referenz/datenmodell.md) | Modelle und Felder | `app/models.py`, `la_tool_admin/models.py` |

## Entscheidungen

Architekturentscheidungen mit Begründung, Alternativen und Umsetzungsschritten:

- [0001 Deployment-Strategie](entscheidungen/0001-deployment-strategie.md) – Docker Compose auf dem VPS (umgesetzt 11.11.2026)

## Berichte

Momentaufnahmen mit Datum, werden nicht fortgeschrieben:

- [Audit vom 09.11.2026](berichte/audit-2026-11-09.md) – Sicherheit, UX, Performance, Go-Live-Checkliste

## Aufbau dieser Dokumentation

Die Gliederung folgt den Lesergruppen und dem tatsächlichen Projekt (ein Django-Monolith auf einem VPS, Zielbild Docker Compose):

- **Architektur** beschreibt das *Was und Warum*, die Leitfäden **Entwicklung**, **Deployment** und **Betrieb** das *Wie* für Entwickler bzw. Administratoren.
- **Referenzen** sind tabellarisch und eng an den Code gebunden; die Leitfäden verweisen auf sie statt Werte zu wiederholen.
- **Entscheidungen** begründen Weichenstellungen; überholte Entscheidungen werden durch neue ersetzt, nicht umgeschrieben.
- **Berichte** halten einen Stand fest und werden bei Änderungen nicht angepasst.

Bei Änderungen am Code die betroffene Referenz und ggf. den Leitfaden im selben Commit aktualisieren.
