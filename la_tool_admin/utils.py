from django.conf import settings
from django.contrib.auth.models import Group

from .models import AutoGroupRule, PinnedGroup, Profile


def _desired_from_rule(has_ids, known_ids, rule_ids, normalize):
    """True/False, ob eine Regelseite greift; None, wenn die Daten dieser Quelle unbekannt sind."""
    if not rule_ids:
        return False
    if not has_ids:
        return None
    return bool({normalize(x) for x in known_ids if x is not None} & {normalize(x) for x in rule_ids if x is not None})


def sync_idp_groups(user):
    """Gruppen aus den Identity-Providern (Entra, Divera) übernehmen.

    Quellen: zuletzt bekannte Entra-Gruppen und Divera-Qualifikationen am Profil, Auto-Gruppen-Regeln
    und das Legacy-Mapping AZURE_GROUPS_MAPPING. Grundsätze:
      - Eine Gruppe wird hinzugefügt, sobald eine bekannte Quelle sie vergibt.
      - Entfernt wird nur, wenn alle beteiligten Quellen bekannt sind und keine sie vergibt –
        fehlen Daten einer Quelle (z.B. nie per Entra angemeldet), bleibt die Mitgliedschaft.
      - Lokal festgesetzte Gruppen (PinnedGroup) werden nie entfernt.
    """
    profile = Profile.objects.filter(user=user).first()
    divera_quals = profile.divera_qualifications if profile else None
    entra_ids = profile.entra_group_ids if profile else None
    pinned = set(PinnedGroup.objects.filter(user=user).values_list('group_id', flat=True))

    desired = {}  # group -> True (hinzufügen) / False (entfernen) / None (unbekannt, nichts tun)

    for rule in AutoGroupRule.objects.select_related('group'):
        sides = [
            _desired_from_rule(divera_quals is not None, divera_quals or [], rule.divera_qual_ids, int),
            _desired_from_rule(entra_ids is not None, entra_ids or [], rule.entra_group_ids, lambda x: str(x).lower()),
        ]
        if not rule.divera_qual_ids and not rule.entra_group_ids:
            continue  # leere Regel würde alle treffen
        if True in sides:
            desired[rule.group] = True
        elif None in sides:
            desired.setdefault(rule.group, None)
        else:
            desired.setdefault(rule.group, False)

    # Legacy: feste Zuordnung Entra-Gruppe → Django-Gruppe (.env), nur für Nutzer mit bekannten Entra-Gruppen
    mapping = {k: v for k, v in getattr(settings, 'AZURE_GROUPS_MAPPING', {}).items() if k}
    if entra_ids is not None and mapping:
        entra_set = {str(x).lower() for x in entra_ids}
        for azure_id, name in mapping.items():
            group, _ = Group.objects.get_or_create(name=name)
            if azure_id.lower() in entra_set:
                desired[group] = True
            elif desired.get(group) is not True:
                desired[group] = False

    for group, wanted in desired.items():
        if wanted:
            user.groups.add(group)
        elif wanted is False and group.pk not in pinned:
            user.groups.remove(group)


def pin_group(user, group, by=None):
    """Mitgliedschaft lokal festsetzen (und sicherstellen, dass sie besteht)."""
    user.groups.add(group)
    PinnedGroup.objects.get_or_create(user=user, group=group, defaults={'created_by': by})


def unpin_group(user, group, remove=False):
    PinnedGroup.objects.filter(user=user, group=group).delete()
    if remove:
        user.groups.remove(group)
