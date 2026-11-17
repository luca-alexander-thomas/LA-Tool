# Datenmodell

Alle Modelle der Apps `app` und `la_tool_admin` (Stand der Modelle im Code; Felder `id` weggelassen). Überblick und Zusammenhänge: [Architektur](../architektur.md#datenmodell).

## Inhalte (`app`)

| Modell | Felder | Hinweise |
|---|---|---|
| `Levels` | `name`, `slug` (eindeutig), `order`, `icon`, `badge_bg_class`, `badge_text_class`, `default_training_count`, `default_training_pass_pct`, `default_exam_count`, `default_exam_pass_pct`, `is_draft` | LA-Stufe. `default_exam_pass_pct` ist auch Grenze der Ampel „Bereit fürs LA“. Icons werden beim Speichern verkleinert |
| `Questions_Catalogs` | `title`, `short_title`, `order`, `level`→Levels, `multi_answer_scoring` (`all_or_nothing`/`partial`), `meta_reference`, `meta_time`, `is_draft` | Katalog (Lernabschnitt) einer Stufe; sortiert nach `order`, `title` |
| `Questions_Theory` | `number`, `question`, `catalog`→Catalogs, `answer_choice` (Liste), `answer_correct` (Liste richtiger Texte), `answer_text` (Altfeld: einzelne richtige Antwort), `help_reference`, `meta_reference`, `meta_time`, `is_draft` | Theoriefrage; Antwort-Buchstaben = Position in `answer_choice` |
| `Questions_Practical` | `number`, `question`, `catalog`→Catalogs, `file` (PDF/PNG/JPG), `help_reference`, `meta_*`, `is_draft` | Praxisaufgabe; Datei wird beim Löschen entfernt, wenn keine andere Aufgabe sie nutzt |
| `Questions_GroupExercise` | `number`, `question`, `level`→Levels (leer = alle Stufen), `catalog` (veraltet, nicht editierbar), `file`, `help_reference`, `meta_*`, `is_draft` | Gruppenaufgabe |
| `Exams` | `name`, `level`, `catalog` (ungenutzt in der Oberfläche), `time_in_min`, `pass_threshold` (Punkte), `info_text`, `end_text`, `visible`, `closed`, `archived`, `assigned_users`, `assigned_groups`, `questions`→Theory | Übungsprüfung |
| `Work` | `title`, `date`, `date_end`, `location`, `description`, `level`, `divera_id`, `created_at`, `created_user`, `is_manual`, `is_draft`, `theory_questions`, `practical_exercises`, `group_exercises`, `groups` | Dienst; `divera_id` verbindet mit dem Divera-Termin; ohne `groups` für alle sichtbar |
| `LearningAssignment` | `title`, `description`, `level`, `catalogs` (leer = alle der Stufe), `target_pct`, `due_date`, `work`, `assigned_users`, `assigned_groups`, `created_by`, `created_at` | Lernauftrag; Frist = `due_date` oder Tag des Dienstes; ohne Zuweisung für alle |
| `SiteSettings` | `training_pass_threshold`, `notice_text`, `notice_level` (`info`/`warning`), `notice_visibility` (`off`/`public`/`users`) | Einzeilige Tabelle (`SiteSettings.get()`); Hinweisbanner der Startseite (`notice_for(user)`); trägt außerdem die App-Berechtigungen (`Meta.permissions`) |

## Ergebnisse und Nutzerdaten (`app`)

| Modell | Felder | Hinweise |
|---|---|---|
| `TrainingResultData` | `name`, `questions` (Liste IDs), `answers` ({ID: [Buchstaben]}), `meta_reference` ({score, total}), `meta_time`, `user` (leer bei anonymem Training) | Grundlage für Lernstand und Lernkartei |
| `ExamAttempt` | `user`, `exam`, `question_ids`, `answers` (Zwischenstand), `started_at` | Laufender Prüfungsversuch, eindeutig je Person und Prüfung; wird bei Abgabe gelöscht |
| `ExamResultData` | `name`, `questions`, `answers`, `meta_reference` ({score, total, passed, level}), `meta_time`, `user`, `exam`, `state` (`hidden`/`published`/`archived`) | Prüfungsergebnis; sichtbar für die Person erst bei `published` |
| `PracticalSelfAssessment`, `GroupExerciseSelfAssessment` | `user`, `question`, `score` (0–100), `updated_at` | Selbsteinschätzung, eindeutig je Person und Aufgabe |
| `QuestionBookmark` | `user`, `question`, `created_at` | Gemerkte Frage |
| `QuestionReport` | `question`, `user`, `message`, `created_at`, `resolved_at`, `resolved_by` | Fehlermeldung zu einer Frage |

## Konten (`la_tool_admin`)

| Modell | Felder | Hinweise |
|---|---|---|
| `Profile` | `user` (1:1), `login_source` (`local`/`divera`/`entra`), `divera_ucr`, `divera_qualifications`, `divera_groups`, `divera_left_at`, `divera_listed`, `entra_oid`, `entra_group_ids`, `learning_reminders`, `last_learning_reminder_at` | Zusatzdaten zum Django-`User`. `divera_left_at` gesetzt = wegen Austritt gesperrt; `divera_listed` = stand schon in der Divera-Personenliste |
| `DiveraQualification` | `qual_id`, `name`, `short_name` | Namen der Divera-Qualifikationen aus `cluster.qualification` (bei Divera-Anmeldung und nächtlichem Abgleich gefüllt); Auswahl bei Auto-Gruppen |
| `AutoGroupRule` | `group` (1:1), `divera_qual_ids`, `entra_group_ids` | Regel für automatische Gruppenmitgliedschaft |
| `PinnedGroup` | `user`, `group`, `created_by`, `created_at` | Festgesetzte Mitgliedschaft (vom Abgleich nie entfernt) |
| `PushSubscription` | `user`, `endpoint` (eindeutig), `p256dh`, `auth`, `user_agent`, `created_at` | Push-Abo eines Geräts |
| `UserNotification` | `user`, `title`, `body`, `url`, `created_at`, `read_at` | Gespeicherte Benachrichtigung |
| `Changes` | `change`, `datetime`, `username`, `additional_meta` | Ungenutzt (nur im Django-Admin registriert) |

## Signale und Hooks

| Auslöser | Wirkung | Ort |
|---|---|---|
| `Levels` gespeichert/gelöscht | Cache der freigegebenen Stufen leeren | `app/models.py` |
| `Questions_Practical`/`Questions_GroupExercise` gelöscht | Datei löschen, wenn nicht mehrfach genutzt | `app/models.py` |
| `Levels` gelöscht | Icon-Datei löschen | `app/models.py` |
| `post_migrate` (App `app`) | Gruppenaufgaben mit altem Katalog-Bezug auf dessen Stufe umstellen | `app/apps.py` |
