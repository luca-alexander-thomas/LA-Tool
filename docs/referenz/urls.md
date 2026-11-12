# Endpunkte

Alle Routen (`app/urls.py`, `la_tool_admin/urls.py`, `la_tool/urls.py`). Das LA-Tool hat **keine öffentliche API**; JSON-Endpunkte dienen nur der eigenen Oberfläche, verlangen eine Sitzung und bei POST ein CSRF-Token (Header `X-CSRFToken`).

Legende Zugriff: **öffentlich** = ohne Anmeldung, **angemeldet** = Sitzung nötig, sonst Weiterleitung zu `/login/?next=…`.

## Seiten der App

| Pfad | Name | Zugriff | Inhalt |
|---|---|---|---|
| `/` | `home` | öffentlich | Startseite (angemeldet: Übersicht; ohne Divera-Verknüpfung einmal je Sitzung zum First-Run-Wizard) |
| `/login/`, `/logout/` (POST) | `login`, `logout` | öffentlich | Anmeldung (mit Drosselung), Abmeldung |
| `/microsoft-login/`, `/microsoft-callback/` | `microsoft_login`, `microsoft_callback` | öffentlich | Microsoft-OAuth (PKCE) |
| `/first-run/` | `first_run_wizard` | angemeldet | Divera verknüpfen (Zugangsdaten oder Accesskey) |
| `/profile/` | `profile` | angemeldet | Konto, Push, Lern-Erinnerung, Meine Daten, Trainingsverlauf |
| `/profile/daten/` | `my_data_export` | angemeldet | Download aller eigenen Daten (JSON) |
| `/profile/lerndaten-loeschen/` (POST) | `my_learning_data_delete` | angemeldet | eigene Lerndaten löschen (Feld `confirm=LÖSCHEN`) |
| `/benachrichtigungen/` | `notification_list` | angemeldet | Benachrichtigungen; markiert alle als gelesen |
| `/benachrichtigungen/<id>/` | `notification_open` | angemeldet | markiert gelesen und leitet zum Ziel |
| `/uebungen/` | `excercise` | angemeldet | Übersicht mit „Heute lernen“, Lernaufträgen |
| `/uebungen/theorie/` | `training_config` | öffentlich | Training einstellen (Arten außer „Gemischt“ nur angemeldet) |
| `/uebungen/theorie/heute/` (GET, POST) | `training_today` | angemeldet | „Heute lernen“ starten; POST optional `catalog` oder `assignment` |
| `/uebungen/theorie/training/` | `training_run` | öffentlich | laufender Durchgang; POST `answers` (JSON), für späte Abgaben zusätzlich `run_id`, `question_ids` |
| `/uebungen/theorie/training/<id>/` | `training_result` | angemeldet (eigene) | Auswertung |
| `/uebungen/theorie/training/<id>/wiederholen/` (POST) | `training_retry` | angemeldet (eigene) | Fehler erneut üben |
| `/uebungen/theorie/fragen/` | `theory_lookup` | angemeldet | Nachschlagen mit Lösungen (während einer Prüfung gesperrt) |
| `/uebungen/theorie/lernstand/` | `learning_stats` | angemeldet | Mein Lernstand |
| `/uebungen/praxis/`, `/uebungen/praxis/<id>/` | `practical_list`, `practical_detail` | öffentlich (Selbsteinschätzung angemeldet) | Praxisaufgaben |
| `/uebungen/gruppen/`, `/uebungen/gruppen/<id>/` | `group_list`, `group_detail` | öffentlich (Selbsteinschätzung angemeldet) | Gruppenaufgaben |
| `/pruefungen/` | `exam_list` | angemeldet | zugewiesene Prüfungen, Ergebnisse |
| `/pruefungen/<id>/` | `exam_start` | angemeldet (zugewiesen) | Start bzw. Fortsetzen |
| `/pruefungen/<id>/run/` | `exam_run` | angemeldet (zugewiesen) | Durchführung; POST `action=save` (Zwischenstand, JSON-Antwort) oder Abgabe |
| `/pruefungen/<id>/ergebnis/` | `exam_result` | angemeldet | eigenes Ergebnis (Details erst nach Freigabe) |
| `/dienste/`, `/dienste/<id>/` | `work`, `work_detail` | angemeldet | Dienste (Liste mit `?jahr=`, Kalender), Detail |
| `/dienste/<id>/ueben/` | `work_training_start` | angemeldet | Training mit den Fragen des Dienstes |
| `/la-filter/<slug>/` | `set_la_filter` | öffentlich | aktive LA-Stufe der Sitzung wechseln |
| `/datenschutz/`, `/nutzungsbedingungen/`, `/impressum/` | `legal_privacy`, `legal_terms`, `legal_imprint` | öffentlich | Rechtstexte |
| `/neuigkeiten/` | `release_notes` | öffentlich | installierte Version mit Release-Notizen (aus `release.json`) |

## JSON-Endpunkte

| Pfad | Methode | Zugriff | Anfrage → Antwort |
|---|---|---|---|
| `/uebungen/theorie/fragen/<id>/merken/` | POST | angemeldet | `{"saved": true\|false}` → `{"saved": …}` |
| `/uebungen/theorie/fragen/<id>/melden/` | POST | angemeldet | `{"message": "…"}` → `{"ok": true}`; 400 ohne Text, 429 bei 20 offenen Meldungen |
| `/uebungen/theorie/fragen/offline.json` | GET | angemeldet | Fragen aller freigegebenen Stufen mit Lösungen (ohne persönliche Daten); 403 während einer Prüfung |
| `/push/abonnieren/` | POST | angemeldet | Push-Abo des Browsers (`endpoint`, `keys.p256dh`, `keys.auth`) → `{"ok": true}`; nur bekannte Push-Dienste |
| `/push/abbestellen/` | POST | angemeldet | `{"endpoint": "…"}` → `{"ok": true}` |
| `/push/test/` | POST | angemeldet | Test-Push an die eigenen Geräte |
| `/healthz/` | GET | öffentlich | `{"status": "ok", "version": "<tag>"}` (200; `version` ist `null` ohne Release) oder `{"status": "error"}` (503) |

## Technische Endpunkte

| Pfad | Zweck |
|---|---|
| `/sw.js` | Service Worker (aus Template gerendert, `Cache-Control: no-cache`) |
| `/manifest.webmanifest` | Web-App-Manifest |
| `/offline/` | Offline-Seite (vom Service Worker gecacht) |
| `/uebungen/theorie/fragen/offline/` | Hülle für Nachschlagen ohne Netz (vom Service Worker gecacht) |
| `/robots.txt` | `Disallow: /` |
| `/favicon.ico`, `/apple-touch-icon*.png` | Weiterleitung auf die Icons unter `/static/pwa/` |
| `/static/…` | statische Dateien (WhiteNoise) |
| `/media/…` | Uploads, von Django ausgeliefert (auch ohne `DEBUG`; der Proxy sieht das Container-Volume nicht) |
| `/django-admin/` | Django-Admin, nur mit `DEBUG=True` |

## Admin-Bereich (`/admin/`)

Gewählte Filter der Listen (Kataloge, Gruppenaufgaben, Lernstand, Dienste) merkt sich die Sitzung; Zurück-Links und Weiterleitungen nach Aktionen führen zur gefilterten Liste.

Alle Seiten verlangen eine Anmeldung und das Recht `access_admin`; zusätzlich das genannte Recht (siehe [Rollen und Rechte](../sicherheit-datenschutz.md#rollen-und-rechte)). Ändernde Aktionen nur per POST.

| Pfad | Recht |
|---|---|
| `/admin/` | – |
| `/admin/users/` | `manage_users` (Rechte/Gruppen/Admin-Konten zusätzlich `manage_groups`) |
| `/admin/catalog/`, `/admin/catalog/<id>/` | – (lesen) |
| `/admin/catalog/create/`, `…/<id>/update/`, `…/<id>/delete/` | `manage_catalogs` |
| `/admin/catalog/<id>/sammelaktion/` (POST) | `manage_theory` bzw. `manage_practical` je nach `kind`: ausgewählte Fragen/Aufgaben freigeben, als Entwurf markieren, verschieben, löschen |
| `/admin/catalog/<id>/theory/…` | `manage_theory` |
| `/admin/catalog/<id>/practical/…` | `manage_practical` |
| `/admin/gruppenaufgaben/…` | `manage_group_exercises` |
| `/admin/import/`, `/admin/import/example/<fmt>/` | `manage_theory` |
| `/admin/meldungen/…` | `manage_theory` |
| `/admin/draft/<model>/<id>/toggle/` | Recht des jeweiligen Inhalts |
| `/admin/file-confirm/` | Recht des jeweiligen Inhalts (doppelte Dateien bestätigen) |
| `/admin/exam/` | – (lesen) |
| `/admin/exam/create/`, `…/<id>/`, `…/<id>/delete/`, `…/<id>/toggle/<feld>/` | `manage_exams` |
| `/admin/exam/<id>/results/…` | `view_exam_results` |
| `/admin/exam/<id>/results/<id>/release/` | `release_exam_results` |
| `/admin/work/` | – (lesen) |
| `/admin/work/create/`, `…/<id>/`, `…/<id>/delete/` | `manage_work` |
| `/admin/work/sync/` | `sync_divera_work` |
| `/admin/lernstand/…` | `view_learning_progress` |
| `/admin/lernauftraege/…` | `manage_assignments` |
| `/admin/benachrichtigungen/…` | `send_notifications` |
| `/admin/stufen/` | – (lesen) |
| `/admin/stufen/erstellen/`, `…/<id>/`, `…/<id>/loeschen/` | `manage_levels` |
| `/admin/autogruppen/…` | `manage_groups` (Gruppen, Regeln und Gruppenrechte) |
| `/admin/settings/` | `manage_settings` |
