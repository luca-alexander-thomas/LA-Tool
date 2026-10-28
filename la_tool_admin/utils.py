from .models import AutoGroupRule


def sync_auto_groups(user, divera_qual_ids=None, entra_group_ids=None):
    """
    Re-evaluate every AutoGroupRule and add/remove the user accordingly.

    Called on every login so membership stays in sync with current quals/groups.
    A rule fires when the user has ANY of its listed Divera qual IDs OR ANY of
    its listed Entra group IDs.  Rules with empty lists on both sides are skipped
    (they would match everyone).
    """
    if divera_qual_ids is None:
        divera_qual_ids = []
    if entra_group_ids is None:
        entra_group_ids = []

    divera_set = set(int(x) for x in divera_qual_ids if x is not None)
    entra_set = set(str(x).lower() for x in entra_group_ids if x)

    for rule in AutoGroupRule.objects.select_related('group').all():
        has_divera_rule = bool(rule.divera_qual_ids)
        has_entra_rule = bool(rule.entra_group_ids)

        if not has_divera_rule and not has_entra_rule:
            continue

        qualifies = False

        if has_divera_rule:
            rule_divera = set(int(x) for x in rule.divera_qual_ids if x is not None)
            if divera_set & rule_divera:
                qualifies = True

        if not qualifies and has_entra_rule:
            rule_entra = set(str(x).lower() for x in rule.entra_group_ids if x)
            if entra_set & rule_entra:
                qualifies = True

        if qualifies:
            user.groups.add(rule.group)
        else:
            user.groups.remove(rule.group)
