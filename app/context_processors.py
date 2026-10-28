from app.models import Levels


def _user_has_admin_access(user):
    return user.is_authenticated and user.has_perm('app.access_admin')


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
