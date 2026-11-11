# Sicherheit und Datenschutz

Rollen, Rechte, Kontoverknüpfung, Sicherheitskonfiguration und Umgang mit personenbezogenen Daten. Technischer Hintergrund der Anmeldung: [Architektur](architektur.md#anmeldung-und-konten).

## Rollen und Rechte

Es gibt keine festen Rollen, sondern Einzelrechte (Django-Permissions der App `app`), vergeben an Personen oder Gruppen. Superuser haben alle Rechte.

| Recht (Codename) | Bezeichnung | Erlaubt |
|---|---|---|
| `access_admin` | Admin-Bereich zugreifen | Grundvoraussetzung für jede Seite unter `/admin/` (Übersicht, Listen lesen) |
| `manage_levels` | Stufen verwalten | Stufen anlegen, bearbeiten, löschen |
| `manage_catalogs` | Kataloge verwalten | Kataloge anlegen, bearbeiten, löschen |
| `manage_theory` | Theoriefragen verwalten | Theoriefragen, Fragen-Import, Meldungen zu Fragen |
| `manage_practical` | Praktische Aufgaben verwalten | Praxisaufgaben inkl. Dateien |
| `manage_group_exercises` | Gruppenaufgaben verwalten | Gruppenaufgaben inkl. Dateien |
| `manage_exams` | Prüfungen verwalten | Prüfungen anlegen, zuweisen, sperren, archivieren |
| `view_exam_results` | Prüfungsergebnisse einsehen | Ergebnisse aller Teilnehmenden |
| `release_exam_results` | Prüfungsergebnisse freigeben | Ergebnisse für Teilnehmende sichtbar machen |
| `manage_work` | Dienste verwalten | Dienste bearbeiten, Stufe und Aufgaben zuordnen |
| `sync_divera_work` | Dienste aus Divera synchronisieren | Knopf „Abgleich“ |
| `manage_settings` | Einstellungen verwalten | Admin → Einstellungen |
| `manage_users` | Nutzer verwalten | Benutzerliste, Passwort zurücksetzen, Konten löschen (nicht von Admins) |
| `manage_groups` | Gruppen und Berechtigungen verwalten | Rechte vergeben, Gruppen festsetzen, Admin machen, Autogruppen |
| `send_notifications` | Benachrichtigungen senden | freie Push-Nachrichten |
| `view_learning_progress` | Lernstand einsehen | Lernstand je Person und Katalog |
| `manage_assignments` | Lernaufträge verwalten | Lernaufträge anlegen, Fortschritt ansehen |

Schutzmechanismen:

- Jede Admin-View ist mit `admin_permission_required` geschützt (403 mit Angabe des fehlenden Rechts).
- Rechte- und Gruppenänderungen sowie Eingriffe in Admin-Konten verlangen `manage_groups`.
- Das eigene Konto und Superuser lassen sich in der Benutzerverwaltung nicht ändern.

**Rechte an Gruppen** vergibt Admin → Einstellungen → Gruppen und Rechte (`manage_groups`). Alle Mitglieder erben sie. So erhalten z.&nbsp;B. alle Mitglieder der Entra-Admin-Gruppe (`AZURE_GROUP_ADMINS_ID` → Gruppe `LA-Tool-Admins`, oder eine Auto-Gruppe mit dieser Entra-ID) beim Microsoft-Login ihre Admin-Rechte. Die Liste zeigt alle Gruppen, auch solche ohne Regel.

### Ohne Anmeldung erreichbar

Startseite, Login, Rechtstexte, Theorie-Training (das Ergebnis wird ohne Personenbezug gespeichert und nicht angezeigt), Praxis- und Gruppenaufgaben, `/healthz/`, `/robots.txt`, Manifest, Service Worker, `/media/`. Alles andere (Nachschlagen, Lernstand, Prüfungen, Dienste, Profil, Admin) verlangt eine Anmeldung.

## Konten und Anmeldung

- **Divera-Konten** werden über die feste Divera-ID (UCR) zugeordnet. Ein Divera-Login übernimmt nie ein bestehendes lokales oder Microsoft-Konto mit gleichem Namen.
- Divera-Konten melden sich **immer gegen Divera** an. Das lokal gespeicherte Passwort (nur als Hash) gilt nur, wenn Divera nicht erreichbar ist.
- **Admins mit verknüpftem Microsoft-Konto** melden sich nur über „Mit Microsoft anmelden“ an (Mehrfaktor und Richtlinien von Entra greifen). Admins ohne Microsoft-Konto, z.&nbsp;B. der lokale Notfall-Superuser, sind ausgenommen.
- **Microsoft:** nur Konten des eigenen Tenants, keine Gastkonten; Zuordnung über die feste Entra-ID.
- **Austritt:** Wer nicht mehr im Divera-Standort ist, wird beim Login bzw. vom nächtlichen Abgleich gesperrt und bei Rückkehr automatisch entsperrt. Von Admins gesperrte Konten bleiben gesperrt. Ein Jahr nach dem Austritt löscht `cleanup_data` das Konto.
- **Gruppen** kommen aus Entra und Divera ([Architektur](architektur.md#gruppen-und-rechte)). Unter Admin → Benutzer festgesetzte Gruppen und direkt vergebene Einzelrechte ändert der Abgleich nie; manuell hinzugefügte Gruppen und „Admin machen“ sind automatisch festgesetzt.
- **Sitzungen:** mit „Angemeldet bleiben“ 90 Tage, bei Nutzung täglich verlängert; sonst bis zum Schließen des Browsers bzw. der App.

## Sicherheitskonfiguration

| Bereich | Umsetzung | Ort |
|---|---|---|
| Hostnamen | nur `HOSTNAME`/`EXTRA_HOSTS` (mit `DEBUG` alle) | `la_tool/settings.py` |
| Cookies | `Secure` in Produktion, `HttpOnly`, `SameSite=Lax` | `settings.py` |
| HTTPS | HSTS 1 Jahr (bei HTTPS hinter dem Proxy), optional `SECURE_SSL_REDIRECT` | `settings.py`, `.env` |
| Header | CSP (nur eigene Quellen), `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, `Cross-Origin-Opener-Policy`, `nosniff` | `settings.py` |
| CSRF | alle Formulare und JSON-POSTs mit Token; Logout nur per POST | Templates, `app.js` |
| Login | max. 5 Fehlversuche je Benutzername / 30 je IP in 15 Minuten (HTTP 429) | `app/login_function.py` |
| OAuth | PKCE, State, Nonce; Tenant-Prüfung | `la_tool_admin/views.py` |
| Uploads | nur PDF/PNG/JPG; Fragen-Import max. 5 MB / 2000 Zeilen, atomar | `models.py`, `la_tool_admin/views.py` |
| Weiterleitungen | nur auf eigene Pfade (`safe_next_url`, `safe_internal_url`) | `login_function.py`, `push.py` |
| Push | nur an bekannte Push-Dienste (Schutz vor SSRF), max. 10 Geräte je Person | `la_tool_admin/push.py` |
| Prüfungen | Zeit serverseitig, Lösungen erst nach Freigabe, Training/Nachschlagen während einer Prüfung gesperrt, „Gesperrt“ beendet laufende Versuche | `app/views.py` |
| Suchmaschinen | `robots.txt` mit `Disallow: /`, `noindex` | `app/views.py`, `base.html` |

Die CSP erlaubt `'unsafe-inline'` (Inline-Skripte in Templates) und `'unsafe-eval'` (Alpine.js). Fremde Quellen sind gesperrt; neue Bibliotheken deshalb lokal ablegen.

Prüfung mit Produktionswerten: `python manage.py check --deploy` (erwartete Hinweise: `SECURE_HSTS_INCLUDE_SUBDOMAINS` und `SECURE_HSTS_PRELOAD` sind bewusst nicht gesetzt).

## Datenschutz

> Die folgenden Punkte beschreiben die technische Umsetzung. Sie ersetzen keine rechtliche Prüfung.

### Rechtstexte

`/datenschutz/`, `/nutzungsbedingungen/`, `/impressum/` – verlinkt im Footer und auf der Login-Seite. Die Angaben (verantwortliche Stelle, Kontakt, Datenschutzbeauftragte Person, Hoster) stehen in `app/legal_info.py`; solange dort `[BITTE ERGÄNZEN …]` steht, zeigen die Seiten einen Entwurfshinweis. Rechtlich zu prüfende Stellen sind im Text markiert.

### Welche Daten wo liegen

| Daten | Ort | Wer sieht sie |
|---|---|---|
| Konto, Gruppen, Divera-ID und -Qualifikationen, Entra-ID und -Gruppen | Datenbank | Person selbst, Admins (Benutzerverwaltung) |
| Trainings (Antworten, Ergebnis), Merkliste, Selbsteinschätzungen | Datenbank | Person selbst; Lernstand für `view_learning_progress` |
| Prüfungsergebnisse | Datenbank | Person nach Freigabe; `view_exam_results` |
| Meldungen zu Fragen | Datenbank | `manage_theory` |
| Push-Abos, Benachrichtigungen | Datenbank | Person selbst |
| Fehlgeschlagene Anmeldungen (mit IP) | Server-Log | Server-Administration |
| Farbschema, Zwischenstände, Offline-Fragen, offene Trainings | Browser des Geräts | Person selbst; Fragen und offene Trainings werden beim Abmelden gelöscht |

Persönliche Divera-Accesskeys werden nicht gespeichert.

### Rechte der Betroffenen

- **Mein Konto → Meine Daten:** Download aller eigenen Daten als JSON (Punkte nicht freigegebener Prüfungen bleiben verborgen).
- **Lerndaten löschen:** Trainings, Merkliste, Selbsteinschätzungen und Benachrichtigungen; Bestätigung durch Eintippen von „LÖSCHEN“.
- **Konto und Prüfungsergebnisse** löscht ein Admin auf Anfrage (Admin → Benutzer). Divera-Konten entstehen bei der nächsten Divera-Anmeldung neu.

### Löschkonzept

Fristen in `app/legal_info.py` (`RETENTION`), umgesetzt von `python manage.py cleanup_data` (täglich, siehe [Betrieb](betrieb.md#wiederkehrende-aufgaben-timer)):

| Daten | Frist |
|---|---|
| Trainingsergebnisse | 2 Jahre |
| Prüfungsergebnisse | 3 Jahre |
| Konten ausgetretener Mitglieder (inkl. aller Daten) | 1 Jahr nach dem Austritt |
| Benachrichtigungen | 90 Tage |
| Erledigte Meldungen zu Fragen | 1 Jahr |
| Sitzungen | Ablauf der Sitzung (`clearsessions`) |

Änderungen an den Fristen in `RETENTION` vornehmen; die Datenschutzerklärung übernimmt die Werte automatisch.

### Externe Empfänger

Divera 24/7 (Anmeldung, Abgleich), Microsoft Entra ID (Anmeldung, Gruppen), Push-Dienste der Browser-Hersteller (nur bei eingeschaltetem Push, Inhalte verschlüsselt). Kein Tracking, keine Analyse-Dienste, nur technisch notwendige Cookies.
