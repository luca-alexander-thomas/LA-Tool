from app.models import published_levels


def _user_has_admin_access(user):
    return user.is_authenticated and user.has_perm('app.access_admin')


# URL-Name -> Navigationsbereich, damit Templates den aktiven Menüpunkt markieren können
_NAV_SECTIONS = {
    'home': 'home',
    'excercise': 'excercise',
    'training_config': 'theory', 'training_run': 'theory', 'training_result': 'theory', 'theory_lookup': 'lookup',
    'training_today': 'theory', 'training_retry': 'theory', 'learning_stats': 'stats',
    'practical_list': 'practical', 'practical_detail': 'practical',
    'group_list': 'group', 'group_detail': 'group',
    'work': 'work', 'work_detail': 'work', 'work_training_start': 'work',
    'exam_list': 'exam', 'exam_start': 'exam', 'exam_run': 'exam', 'exam_result': 'exam',
    'profile': 'profile', 'first_run_wizard': 'profile',
    'notification_list': 'notifications',
    'admin_index': 'admin_home',
    'admin_users': 'admin_users',
    'admin_catalog': 'admin_catalog', 'admin_catalog_create': 'admin_catalog',
    'admin_catalog_detail': 'admin_catalog', 'admin_catalog_update': 'admin_catalog',
    'admin_theory_create': 'admin_catalog', 'admin_theory_edit': 'admin_catalog',
    'admin_practical_create': 'admin_catalog', 'admin_practical_edit': 'admin_catalog',
    'admin_group_list': 'admin_group', 'admin_group_create': 'admin_group', 'admin_group_edit': 'admin_group',
    'admin_file_confirm': 'admin_catalog',
    'admin_import_questions': 'admin_import',
    'admin_exam_list': 'admin_exam', 'admin_exam_create': 'admin_exam', 'admin_exam_edit': 'admin_exam',
    'admin_exam_results': 'admin_exam', 'admin_exam_result_user': 'admin_exam',
    'admin_work_list': 'admin_work', 'admin_work_create': 'admin_work', 'admin_work_edit': 'admin_work',
    'admin_level_list': 'admin_level', 'admin_level_create': 'admin_level', 'admin_level_edit': 'admin_level',
    'admin_autogroup_list': 'admin_autogroup', 'admin_autogroup_create': 'admin_autogroup',
    'admin_autogroup_edit': 'admin_autogroup',
    'admin_settings': 'admin_settings',
    'admin_push_message': 'admin_push',
    'admin_report_list': 'admin_report',
    'admin_learning': 'admin_learning', 'admin_learning_user': 'admin_learning',
    'admin_assignment_list': 'admin_assignment', 'admin_assignment_create': 'admin_assignment',
    'admin_assignment_detail': 'admin_assignment', 'admin_assignment_edit': 'admin_assignment',
}


# Bereiche unter dem Menüpunkt „Üben“
_PRACTICE_SECTIONS = {'excercise', 'theory', 'lookup', 'stats', 'practical', 'group'}


def nav_section(request):
    match = getattr(request, 'resolver_match', None)
    url_name = match.url_name if match else None
    section = _NAV_SECTIONS.get(url_name, '')
    practice = section in _PRACTICE_SECTIONS
    return {
        'nav_section': section,
        'nav_practice': practice,
        # Unterleiste „Üben“ auf dem Handy; nicht während eines Durchgangs (lenkt ab)
        'practice_subnav': practice and url_name != 'training_run',
    }


def current_la_filter(request):
    """Slug der aktiven LA-Stufe; legt ihn beim ersten Aufruf in der Session ab.

    Views nutzen das statt session['la_filter'] direkt, weil der Context-Processor
    erst nach der View läuft (sonst ist die Session beim ersten Besuch leer).
    """
    return la_filter(request)['la_filter']


def la_filter(request):
    # View und Context-Processor rufen das beide auf: einmal pro Request rechnen
    cached = getattr(request, '_la_filter_context', None)
    if cached is not None:
        return cached
    request._la_filter_context = context = _la_filter(request)
    return context


def _la_filter(request):
    # Nur freigegebene Stufen sind wähl- und sichtbar; eine Entwurfs-Stufe in der Session wird ersetzt
    all_levels = published_levels()
    valid_slugs = {l.slug for l in all_levels}

    # Fehlerseiten können ohne Session/Auth-Middleware gerendert werden
    session = getattr(request, 'session', {})
    user = getattr(request, 'user', None)
    is_authenticated = bool(user and user.is_authenticated)

    level_slug = session.get('la_filter')

    if not level_slug or level_slug not in valid_slugs:
        current_slug = None
        if is_authenticated:
            try:
                current_slug = user.profile.divera_la_level
            except Exception:
                pass

        if current_slug and current_slug in valid_slugs:
            current_obj = next((l for l in all_levels if l.slug == current_slug), None)
            if current_obj:
                next_obj = next((l for l in all_levels if l.order > current_obj.order), None)
                level_slug = next_obj.slug if next_obj else current_obj.slug
            else:
                level_slug = all_levels[0].slug if all_levels else ''
        else:
            level_slug = all_levels[0].slug if all_levels else ''

        if level_slug:
            session['la_filter'] = level_slug

    current_level = next((l for l in all_levels if l.slug == level_slug), None)

    return {
        'la_filter': level_slug or '',
        'current_level': current_level,
        'all_levels': all_levels,
        'user_has_admin_access': is_authenticated and _user_has_admin_access(user),
    }


def push(request):
    from la_tool_admin.push import push_configured
    return {'push_enabled': push_configured()}


DUE_CACHE_SECONDS = 600


def _due_cache_key(user_id):
    return f'due_count:{user_id}'


def forget_due_count(user):
    from django.core.cache import cache
    cache.delete(_due_cache_key(user.pk))


def _due_count(request, user):
    """Heute fällige Wiederholungen der aktiven Stufe (Zahl am Reiter „Üben“), 10 Minuten gecacht.

    Der Cache gilt je Gunicorn-Worker; ein gespeichertes Training leert ihn im eigenen Worker sofort.
    """
    from django.core.cache import cache
    from app import learning
    from app.models import Questions_Catalogs
    level = la_filter(request)['la_filter']
    key = _due_cache_key(user.pk)
    cached = cache.get(key) or {}
    if level not in cached:
        catalogs = list(Questions_Catalogs.objects.filter(level__slug=level, is_draft=False, level__is_draft=False))
        ids = [qid for ids in learning.catalog_question_ids(catalogs).values() for qid in ids]
        cached[level] = len(learning.due_questions(ids, learning.user_attempts(user)))
        cache.set(key, cached, DUE_CACHE_SECONDS)
    return cached[level]


def counters(request):
    """Zähler für Glocke, App-Symbol und Reiter „Üben“ (nur angemeldet)."""
    user = getattr(request, 'user', None)
    if not (user and user.is_authenticated):
        return {}
    from la_tool_admin.push import unread_count
    return {
        'unread_notifications': unread_count(user),
        'due_count': _due_count(request, user),
    }


def release(request):
    """Aktuelle Version (aus dem GitHub-Release) für Fußzeile und Hinweis auf der Startseite."""
    from .release import current_release
    return {'release': current_release()}
