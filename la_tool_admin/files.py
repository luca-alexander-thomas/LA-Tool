"""Dateien im Admin sichten, unbenutzte löschen, Dateien umbenennen (Issue #22).

Pfade aus Anfragen werden nur akzeptiert, wenn sie in der eigenen Liste (list_files) stehen – so kann niemand
über manipulierte Namen außerhalb von MEDIA_ROOT lesen, löschen oder schreiben.
"""
import posixpath

from django.core.exceptions import SuspiciousFileOperation
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.urls import reverse
from django.utils.text import get_valid_filename

from app.media_files import file_fields, used_names

# Zwischenablage für Uploads mit Rückfrage (admin_file_confirm); dort Liegengebliebenes ist immer unbenutzt
TEMP_DIR = 'tmp'


def _walk(path=''):
    dirs, files = default_storage.listdir(path)
    for name in files:
        yield posixpath.join(path, name) if path else name
    for directory in dirs:
        yield from _walk(posixpath.join(path, directory) if path else directory)


def list_files():
    """Alle Dateien unter MEDIA_ROOT mit Ordner, Größe, Änderungszeit und Verwendung, sortiert nach Pfad."""
    used = used_names()
    links = usage_links()
    result = []
    for name in sorted(_walk()):
        try:
            size = default_storage.size(name)
            modified = default_storage.get_modified_time(name)
        except OSError:
            continue
        folder = posixpath.dirname(name)
        result.append({
            'name': name,
            'basename': posixpath.basename(name),
            'folder': folder,
            'size': size,
            'modified': modified,
            'used': name in used,
            'usages': links.get(name, []),
            'temp': folder.split('/')[0] == TEMP_DIR,
            'url': default_storage.url(name),
        })
    return result


def usage_links():
    """{Dateiname: [(Bezeichnung, Link)]} für alle benutzten Dateien."""
    routes = {
        'practical': lambda obj: reverse('admin_practical_edit', args=[obj.catalog_id, obj.pk]),
        'group': lambda obj: reverse('admin_group_edit', args=[obj.pk]),
        'level': lambda obj: reverse('admin_level_edit', args=[obj.pk]),
    }
    labels = {'practical': 'Praxisaufgabe', 'group': 'Gruppenaufgabe', 'level': 'LA-Stufe'}
    links = {}
    for model, field, kind in file_fields():
        for obj in model.objects.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}):
            name = getattr(obj, field).name
            if name:
                links.setdefault(name, []).append((f'{labels[kind]} {obj}', routes[kind](obj)))
    return links


def known_file(name):
    """Den Namen nur zurückgeben, wenn die Datei in der Liste steht (Schutz vor ../ und fremden Pfaden)."""
    return name if name and name in set(_walk()) else None


def delete_files(names):
    """Unbenutzte Dateien löschen. Gibt (gelöscht, übersprungen) als Namenslisten zurück."""
    used = used_names()
    known = set(_walk())
    deleted, skipped = [], []
    for name in names:
        if name not in known or name in used:
            skipped.append(name)
            continue
        default_storage.delete(name)
        deleted.append(name)
        _remove_empty_temp_dir(posixpath.dirname(name))
    return deleted, skipped


def _remove_empty_temp_dir(folder):
    """Leere tmp/<id>-Ordner entfernen (bleiben sonst nach abgebrochenen Uploads liegen)."""
    if folder.split('/')[0] != TEMP_DIR or folder == TEMP_DIR:
        return
    try:
        dirs, files = default_storage.listdir(folder)
        if not dirs and not files:
            default_storage.delete(folder)
    except OSError:
        pass


class RenameError(ValueError):
    pass


def rename_file(name, new_base):
    """Datei umbenennen (Ordner und Endung bleiben) und alle Verweise mitführen. Gibt den neuen Namen zurück."""
    if not known_file(name):
        raise RenameError('Die Datei gibt es nicht mehr.')
    folder = posixpath.dirname(name)
    stem, ext = posixpath.splitext(posixpath.basename(name))
    raw = new_base.strip()
    if ext and raw.lower().endswith(ext.lower()):
        raw = raw[:-len(ext)]  # Endung mit eingegeben: nicht verdoppeln
    try:
        base = get_valid_filename(raw)
    except SuspiciousFileOperation:
        raise RenameError('Bitte einen gültigen Namen eingeben (Buchstaben, Zahlen, - und _).') from None
    new_name = posixpath.join(folder, base + ext) if folder else base + ext
    if new_name == name:
        return name
    if default_storage.exists(new_name):
        raise RenameError(f'Es gibt schon eine Datei „{posixpath.basename(new_name)}“ in diesem Ordner.')
    with default_storage.open(name, 'rb') as source:
        saved = default_storage.save(new_name, File(source))
    if saved != new_name:  # gleichzeitig angelegt: nicht unter fremdem Namen weitermachen
        default_storage.delete(saved)
        raise RenameError('Die Datei konnte nicht umbenannt werden, bitte erneut versuchen.')
    try:
        with transaction.atomic():
            for model, field, _ in file_fields():
                model.objects.filter(**{field: name}).update(**{field: new_name})
    except Exception:
        default_storage.delete(new_name)
        raise
    default_storage.delete(name)
    return new_name
