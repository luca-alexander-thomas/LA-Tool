"""Filter von Listen merken: Zurück-Links und Weiterleitungen führen zur Liste mit den zuletzt gewählten Filtern."""
from django.urls import reverse


def _key(name):
    return f'list-filters:{name}'


def remember_filters(request, name):
    """In der Listen-View aufrufen: aktuelle Filter (Query-String) für die Liste `name` merken."""
    query = request.GET.urlencode()
    if request.session.get(_key(name), '') != query:
        request.session[_key(name)] = query


def filtered_list_url(request, name):
    """URL der Liste `name` mit den zuletzt gemerkten Filtern."""
    query = request.session.get(_key(name), '') if hasattr(request, 'session') else ''
    return reverse(name) + (f'?{query}' if query else '')
