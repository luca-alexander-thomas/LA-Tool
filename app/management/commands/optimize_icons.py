"""Bestehende Stufen-Icons verkleinern und als WebP ablegen (neue Uploads passiert das automatisch)."""
from django.core.management.base import BaseCommand

from app.images import shrink_icon
from app.models import Levels


class Command(BaseCommand):
    help = 'Verkleinert vorhandene Stufen-Icons (max. 160 px, WebP).'

    def handle(self, *args, **options):
        changed = 0
        for model in (Levels,):
            for obj in model.objects.exclude(icon='').exclude(icon__isnull=True):
                old = obj.icon.name
                # save() verkleinert über shrink_icon; die alte Datei wird gelöscht, wenn sie sonst niemand nutzt
                in_use = lambda name, pk=obj.pk, m=model: m.objects.filter(icon=name).exclude(pk=pk).exists()
                if shrink_icon(obj.icon, in_use):
                    model.objects.filter(pk=obj.pk).update(icon=obj.icon.name)
                    changed += 1
                    self.stdout.write(f'{model.__name__} {obj.pk}: {old} -> {obj.icon.name}')
        self.stdout.write(self.style.SUCCESS(f'{changed} Icon(s) optimiert.'))
