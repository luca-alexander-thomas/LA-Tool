"""Hochgeladene Dateien (MEDIA_ROOT): wer nutzt welche Datei (Issue #22).

Alle Dateifelder der App stehen in FILE_FIELDS. Eine Datei gilt als benutzt, sobald irgendein Datensatz in einem
dieser Felder auf sie zeigt – modellübergreifend, damit z.B. beim Löschen einer Aufgabe keine Datei verschwindet,
die eine andere Aufgabe oder Stufe noch braucht.
"""
from django.apps import apps

# (App-Label.Modell, Feld, Bereich fürs Protokoll/Links)
FILE_FIELDS = [
    ('app.Questions_Practical', 'file', 'practical'),
    ('app.Questions_GroupExercise', 'file', 'group'),
    ('app.Levels', 'icon', 'level'),
]


def file_fields():
    """(Modell, Feld, Bereich) aller Dateifelder."""
    for label, field, kind in FILE_FIELDS:
        yield apps.get_model(label), field, kind


def usages(name):
    """[(Bereich, Objekt)] aller Datensätze, die die Datei `name` nutzen."""
    if not name:
        return []
    return [(kind, obj) for model, field, kind in file_fields() for obj in model.objects.filter(**{field: name})]


def in_use(name, exclude=None):
    """True, wenn ein Datensatz (außer `exclude`) die Datei nutzt."""
    if not name:
        return False
    for model, field, _ in file_fields():
        qs = model.objects.filter(**{field: name})
        if exclude is not None and isinstance(exclude, model):
            qs = qs.exclude(pk=exclude.pk)
        if qs.exists():
            return True
    return False


def used_names():
    """Menge aller benutzten Dateinamen."""
    names = set()
    for model, field, _ in file_fields():
        names.update(n for n in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True})
                     .values_list(field, flat=True) if n)
    return names


def delete_if_unused(name, exclude=None):
    """Datei löschen, wenn sie niemand (außer `exclude`) mehr nutzt. Gibt True zurück, wenn gelöscht."""
    from django.core.files.storage import default_storage
    if name and not in_use(name, exclude=exclude) and default_storage.exists(name):
        default_storage.delete(name)
        return True
    return False
