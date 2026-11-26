"""{% edit_hint obj %}: „Zuletzt bearbeitet von … am …“ unter der Überschrift von Admin-Bearbeiten-Seiten (Issue #16).

Sichtbar für jeden Admin; den Link zum Verlauf sieht nur, wer das Änderungsprotokoll einsehen darf.
"""
from urllib.parse import urlencode

from django import template
from django.urls import reverse

from ..edit_log import last_edit, target_type_of

register = template.Library()


@register.inclusion_tag('_edit_hint.html', takes_context=True)
def edit_hint(context, obj):
    entry = last_edit(obj) if obj else None
    user = context.get('user')
    can_view = bool(entry and user and user.has_perm('app.view_edit_log'))
    return {
        'entry': entry,
        'log_url': f"{reverse('admin_edit_log')}?{urlencode({'typ': target_type_of(obj), 'id': obj.pk})}" if can_view else '',
    }
