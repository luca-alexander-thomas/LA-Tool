from app.models import Levels


def _user_has_admin_access(user):
    return user.is_authenticated and user.has_perm('app.access_admin')


# URL-Name -> Navigationsbereich, damit Templates den aktiven Menüpunkt markieren können
_NAV_SECTIONS = {
    'home': 'home',
    'excercise': 'excercise',
    'training_config': 'theory', 'training_run': 'theory', 'training_result': 'theory',
    'practical_list': 'practical', 'practical_detail': 'practical',
    'group_list': 'group', 'group_detail': 'group',
    'work': 'work', 'work_detail': 'work', 'work_training_start': 'work',
    'exam_list': 'exam', 'exam_start': 'exam', 'exam_run': 'exam', 'exam_result': 'exam',
    'profile': 'profile', 'first_run_wizard': 'profile',
    'admin_index': 'admin_home',
    'admin_users': 'admin_users',
    'admin_catalog': 'admin_catalog', 'admin_catalog_create': 'admin_catalog',
    'admin_catalog_detail': 'admin_catalog', 'admin_catalog_update': 'admin_catalog',
    'admin_theory_create': 'admin_catalog', 'admin_theory_edit': 'admin_catalog',
    'admin_practical_create': 'admin_catalog', 'admin_practical_edit': 'admin_catalog',
    'admin_group_create': 'admin_catalog', 'admin_group_edit': 'admin_catalog',
    'admin_file_confirm': 'admin_catalog',
    'admin_import_questions': 'admin_import',
    'admin_exam_list': 'admin_exam', 'admin_exam_create': 'admin_exam', 'admin_exam_edit': 'admin_exam',
    'admin_exam_results': 'admin_exam', 'admin_exam_result_user': 'admin_exam',
    'admin_work_list': 'admin_work', 'admin_work_create': 'admin_work', 'admin_work_edit': 'admin_work',
    'admin_level_list': 'admin_level', 'admin_level_create': 'admin_level', 'admin_level_edit': 'admin_level',
    'admin_autogroup_list': 'admin_autogroup', 'admin_autogroup_create': 'admin_autogroup',
    'admin_autogroup_edit': 'admin_autogroup',
    'admin_settings': 'admin_settings',
}


def nav_section(request):
    match = getattr(request, 'resolver_match', None)
    return {'nav_section': _NAV_SECTIONS.get(match.url_name if match else None, '')}


def current_la_filter(request):
    """Slug der aktiven LA-Stufe; legt ihn beim ersten Aufruf in der Session ab.

    Views nutzen das statt session['la_filter'] direkt, weil der Context-Processor
    erst nach der View läuft (sonst ist die Session beim ersten Besuch leer).
    """
    return la_filter(request)['la_filter']


def la_filter(request):
    all_levels = list(Levels.objects.order_by('order'))
    valid_slugs = {l.slug for l in all_levels}

    level_slug = request.session.get('la_filter')

    if not level_slug or level_slug not in valid_slugs:
        current_slug = None
        if request.user.is_authenticated:
            try:
                current_slug = request.user.profile.divera_la_level
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
            request.session['la_filter'] = level_slug

    current_level = next((l for l in all_levels if l.slug == level_slug), None)

    return {
        'la_filter': level_slug or '',
        'current_level': current_level,
        'all_levels': all_levels,
        'user_has_admin_access': _user_has_admin_access(request.user),
    }
