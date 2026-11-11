from django.apps import AppConfig
from django.db.models.signals import post_migrate


def detach_group_exercises(sender, **kwargs):
    """Gruppenaufgaben von Katalogen lösen: Stufe des Katalogs übernehmen, Katalog-Bezug leeren.

    Läuft nach jedem migrate (stammt aus der Zeit vor versionierten Migrationen) und ist idempotent.
    """
    from .models import Questions_GroupExercise
    for exercise in Questions_GroupExercise.objects.filter(catalog__isnull=False).select_related('catalog'):
        if exercise.level_id is None:
            exercise.level_id = exercise.catalog.level_id
        exercise.catalog = None
        exercise.save(update_fields=['level', 'catalog'])


class AppConfig(AppConfig):
    name = 'app'

    def ready(self):
        post_migrate.connect(detach_group_exercises, sender=self)
