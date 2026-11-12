from django import template

from app.list_filters import filtered_list_url

register = template.Library()


@register.simple_tag(takes_context=True)
def list_url(context, name):
    """{% list_url 'admin_catalog' %}: Liste mit den zuletzt gewählten Filtern."""
    return filtered_list_url(context['request'], name)
