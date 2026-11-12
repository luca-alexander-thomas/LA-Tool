"""Aktuelle Version: release.json schreibt der Deploy-Workflow aus dem GitHub-Release (Tag, Titel, Notizen).

Die Datei liegt im Projektverzeichnis und wird ins Image gebaut; ohne sie (Entwicklung) gibt es keine Version.
"""
import json
import logging
import re
from functools import lru_cache

from django.conf import settings
from django.utils.dateparse import parse_datetime
from django.utils.html import escape
from django.utils.safestring import mark_safe

logger = logging.getLogger(__name__)

RELEASE_FILE = settings.BASE_DIR / 'release.json'


@lru_cache(maxsize=1)
def current_release():
    """{'tag', 'name', 'body', 'published_at', 'url'} oder None."""
    try:
        data = json.loads(RELEASE_FILE.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        logger.warning('release.json ist nicht lesbar')
        return None
    tag = str(data.get('tag') or '').strip()
    if not tag:
        return None
    return {
        'tag': tag,
        'name': str(data.get('name') or '').strip() or tag,
        'body': str(data.get('body') or ''),
        'published_at': parse_datetime(str(data.get('published_at') or '')),
        'url': str(data.get('url') or '') if str(data.get('url') or '').startswith('https://github.com/') else '',
    }


_INLINE = [
    (re.compile(r'`([^`]+)`'), r'<code>\1</code>'),
    (re.compile(r'\*\*([^*]+)\*\*'), r'<strong>\1</strong>'),
    (re.compile(r'\[([^\]]+)\]\((https://[^\s)]+)\)'), r'<a class="link" href="\2" rel="noopener" target="_blank">\1</a>'),
    (re.compile(r'(?<![">])(https://[^\s<]+)'), r'<a class="link" href="\1" rel="noopener" target="_blank">\1</a>'),
]


def _inline(text):
    html = escape(text)
    for pattern, repl in _INLINE:
        html = pattern.sub(repl, html)
    return html


def notes_html(body):
    """Release-Notizen (GitHub-Markdown, Teilmenge) als HTML: Überschriften, Listen, Absätze, fett, Code, Links.

    Alles wird zuerst escaped; nur die hier erzeugten Tags sind HTML.
    """
    out, para, in_list = [], [], False

    def flush_para():
        if para:
            out.append(f'<p>{_inline(" ".join(para))}</p>')
            para.clear()

    def close_list():
        nonlocal in_list
        if in_list:
            out.append('</ul>')
            in_list = False

    for raw in (body or '').replace('\r\n', '\n').split('\n'):
        line = raw.strip()
        heading = re.match(r'^(#{1,6})\s+(.*)$', line)
        item = re.match(r'^[-*+]\s+(.*)$', line)
        if not line or line.startswith('<!--'):
            flush_para()
            close_list()
        elif heading:
            flush_para()
            close_list()
            tag = 'h2' if len(heading.group(1)) <= 2 else 'h3'
            out.append(f'<{tag}>{_inline(heading.group(2))}</{tag}>')
        elif item:
            flush_para()
            if not in_list:
                out.append('<ul>')
                in_list = True
            out.append(f'<li>{_inline(item.group(1))}</li>')
        else:
            close_list()
            para.append(line)
    flush_para()
    close_list()
    return mark_safe('\n'.join(out))
