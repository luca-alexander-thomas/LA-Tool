"""Hochgeladene Icons klein halten: sie werden nur in Listen und Navigation (max. ca. 60 px) angezeigt."""
import io
import os

from django.core.files.base import ContentFile
from PIL import Image, ImageOps

ICON_MAX_PX = 160


def shrink_icon(field, in_use_elsewhere=lambda name: False, max_px=ICON_MAX_PX):
    """Verkleinert das Bild eines ImageFields auf max_px (längste Seite) und legt es als WebP ab.

    Muss vor dem Speichern des Models aufgerufen werden. Die alte Datei wird gelöscht, wenn sie schon
    gespeichert war und kein anderer Datensatz sie nutzt. Gibt True zurück, wenn ersetzt wurde.
    """
    if not field:
        return False
    # Bereits optimierte, gespeicherte Datei: nicht bei jedem Speichern erneut öffnen
    if field._committed and field.name.lower().endswith('.webp'):
        return False
    try:
        field.open('rb')
        with Image.open(field) as image:
            if image.format == 'WEBP' and max(image.size) <= max_px:
                return False
            image = ImageOps.exif_transpose(image)
            if image.mode not in ('RGB', 'RGBA'):
                image = image.convert('RGBA')
            image.thumbnail((max_px, max_px), Image.LANCZOS)
            buffer = io.BytesIO()
            image.save(buffer, 'WEBP', quality=85, method=6)
    except (OSError, ValueError):
        return False  # kein lesbares Bild: unverändert lassen
    finally:
        field.close()

    was_stored = field._committed
    old_name = field.name
    base = os.path.splitext(os.path.basename(old_name))[0]
    field.save(base + '.webp', ContentFile(buffer.getvalue()), save=False)
    if was_stored and old_name != field.name and not in_use_elsewhere(old_name):
        field.storage.delete(old_name)
    return True
