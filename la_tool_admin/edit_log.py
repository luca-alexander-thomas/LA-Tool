"""Änderungsprotokoll für Stammdaten (Issue #16).

Muster in den Admin-Views:
    before = snapshot(obj)          # vor dem Speichern (bei Neuanlage entfällt das)
    ... speichern ...
    log_edit(request.user, obj, 'update', diff(before, snapshot(obj)))

Jeder Admin sieht unter den Bearbeiten-Seiten „Zuletzt bearbeitet von …“ ({% edit_hint obj %}); das volle Protokoll
braucht das Recht app.view_edit_log (Superuser haben es immer).
"""
import json
from datetime import date, datetime

from django.db import models
from django.db.models.fields.files import FieldFile
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from .models import EditLogEntry

# Modellname → Bereich im Protokoll
TARGET_TYPES = {
    'Questions_Catalogs': 'catalog',
    'Questions_Theory': 'theory',
    'Questions_Practical': 'practical',
    'Questions_GroupExercise': 'group',
    'Exams': 'exam',
    'Work': 'work',
    'Levels': 'level',
    'LearningAssignment': 'assignment',
    'Group': 'autogroup',
    'SiteSettings': 'settings',
}

TARGET_LABELS = {
    'catalog': 'Katalog',
    'theory': 'Theoriefrage',
    'practical': 'Praxisaufgabe',
    'group': 'Gruppenaufgabe',
    'exam': 'Prüfung',
    'work': 'Dienst',
    'level': 'LA-Stufe',
    'assignment': 'Lernauftrag',
    'autogroup': 'Gruppe',
    'settings': 'Einstellungen',
    'file': 'Datei',
}

# Lesbare Feldnamen; nicht aufgeführte Felder erscheinen mit ihrem Namen
FIELD_LABELS = {
    'title': 'Titel', 'short_title': 'Kurztitel', 'name': 'Name', 'slug': 'Slug', 'order': 'Reihenfolge',
    'level': 'Stufe', 'catalog': 'Katalog', 'is_draft': 'Entwurf', 'number': 'Nummer', 'question': 'Frage',
    'answer_choice': 'Antworten', 'answer_correct': 'Richtige Antworten', 'answer_text': 'Antworttext',
    'help_reference': 'Hinweis', 'file': 'Datei', 'icon': 'Logo', 'description': 'Beschreibung',
    'multi_answer_scoring': 'Wertung Mehrfachauswahl', 'time_in_min': 'Zeit (Min.)',
    'pass_threshold': 'Bestehensgrenze', 'info_text': 'Infotext', 'end_text': 'Abschlusstext',
    'visible': 'Sichtbar', 'closed': 'Geschlossen', 'archived': 'Archiviert', 'questions': 'Fragen',
    'assigned_users': 'Personen', 'assigned_groups': 'Gruppen', 'groups': 'Gruppen', 'date': 'Datum',
    'location': 'Ort', 'theory_questions': 'Theoriefragen', 'practical_exercises': 'Praxisaufgaben',
    'target_pct': 'Ziel (%)', 'due_date': 'Frist', 'work': 'Dienst', 'catalogs': 'Kataloge',
    'badge_bg_class': 'Hintergrundfarbe', 'badge_text_class': 'Textfarbe',
    'default_training_count': 'Standard Trainingsanzahl', 'default_training_pass_pct': 'Bestehensgrenze Training (%)',
    'default_exam_count': 'Standard Prüfungsanzahl', 'default_exam_pass_pct': 'Bestehensgrenze Prüfung (%)',
    'training_pass_threshold': 'Globale Bestehensgrenze (%)', 'notice_text': 'Hinweistext',
    'notice_level': 'Art des Hinweises', 'notice_visibility': 'Hinweis sichtbar',
    'divera_qual_ids': 'Divera-Qualifikationen', 'entra_group_ids': 'Entra-Gruppen', 'permissions': 'Rechte',
}

# Technische Felder, die nicht protokolliert werden
SKIPPED_FIELDS = {'id', 'meta_time', 'meta_reference', 'created_at', 'created_user', 'created_by'}

MAX_VALUE_LENGTH = 300


def format_value(value):
    """Wert lesbar und gekürzt für das Protokoll."""
    if value is None:
        text = ''
    elif isinstance(value, bool):
        text = 'ja' if value else 'nein'
    elif isinstance(value, FieldFile):
        text = value.name or ''
    elif isinstance(value, datetime):
        text = timezone.localtime(value).strftime('%d.%m.%Y %H:%M') if timezone.is_aware(value) else value.strftime('%d.%m.%Y %H:%M')
    elif isinstance(value, date):
        text = value.strftime('%d.%m.%Y')
    elif isinstance(value, (list, tuple, set)):
        text = ', '.join(format_value(v) for v in value)
    elif isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text if len(text) <= MAX_VALUE_LENGTH else text[:MAX_VALUE_LENGTH - 1] + '…'


def snapshot(obj, extra=None, fields=None):
    """Felder eines Objekts als {Feldname: Text}; Mehrfachbeziehungen als sortierte Namensliste.

    fields: nur diese Felder (z.B. beim Divera-Abgleich), sonst alle außer SKIPPED_FIELDS.
    """
    data = {}
    wanted = (lambda name: name in fields) if fields else (lambda name: name not in SKIPPED_FIELDS)
    for field in obj._meta.concrete_fields:
        if wanted(field.name):
            data[field.name] = format_value(getattr(obj, field.name))
    if obj.pk:
        for field in obj._meta.many_to_many:
            if wanted(field.name):
                data[field.name] = format_value(sorted(str(item) for item in getattr(obj, field.name).all()))
    data.update(extra or {})
    return data


def diff(before, after):
    """{Feldname: [alt, neu]} für alle geänderten Felder."""
    return {key: [before.get(key, ''), after.get(key, '')]
            for key in sorted(set(before) | set(after)) if before.get(key, '') != after.get(key, '')}


def target_type_of(obj):
    return TARGET_TYPES[type(obj).__name__]


def log_edit(user, target, action, changes=None, *, target_type=None, target_id=None, label='', user_name=''):
    """Eintrag schreiben. target: Modellobjekt oder None (dann target_type/target_id/label angeben).

    user: angemeldete Person oder None für automatische Änderungen (dann user_name, z.B. „Divera-Abgleich“).
    """
    if isinstance(target, models.Model):
        target_type = target_type or target_type_of(target)
        target_id = target.pk
        label = label or str(target)
    person = user if getattr(user, 'is_authenticated', False) else None
    if person is not None:
        user_name = person.get_full_name() or person.get_username()
    return EditLogEntry.objects.create(
        user=person,
        user_name=(user_name or 'System')[:150],
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_label=format_value(label)[:200],
        changes=changes or {},
    )


def last_edit(obj):
    """Letzter Protokolleintrag zu einem Objekt oder None."""
    if obj is None or not getattr(obj, 'pk', None):
        return None
    return EditLogEntry.objects.filter(target_type=target_type_of(obj), target_id=obj.pk).first()


def field_label(name):
    return FIELD_LABELS.get(name, name)


def target_url(entry, theory_catalogs=None):
    """Link zum Objekt eines Eintrags (None, wenn es keine eigene Seite hat oder gelöscht ist)."""
    routes = {
        'catalog': ('admin_catalog_detail', lambda i: [i]),
        'group': ('admin_group_edit', lambda i: [i]),
        'exam': ('admin_exam_edit', lambda i: [i]),
        'work': ('admin_work_edit', lambda i: [i]),
        'level': ('admin_level_edit', lambda i: [i]),
        'assignment': ('admin_assignment_detail', lambda i: [i]),
        'autogroup': ('admin_autogroup_edit', lambda i: [i]),
    }
    if entry.action == 'delete':
        return None
    if entry.target_type == 'settings':
        return reverse('admin_settings')
    if entry.target_type in ('theory', 'practical') and theory_catalogs:
        catalog_id = theory_catalogs.get((entry.target_type, entry.target_id))
        if catalog_id:
            name = 'admin_theory_edit' if entry.target_type == 'theory' else 'admin_practical_edit'
            return reverse(name, args=[catalog_id, entry.target_id])
        return None
    if entry.target_type in routes and entry.target_id:
        name, args = routes[entry.target_type]
        try:
            return reverse(name, args=args(entry.target_id))
        except NoReverseMatch:
            return None
    return None
