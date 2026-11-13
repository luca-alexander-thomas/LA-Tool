from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.contrib import auth, messages
from django.conf import settings
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from app import learning
from app.models import (
    Questions_Catalogs, Questions_Theory, Questions_Practical,
    Questions_GroupExercise, Exams, ExamResultData, Work, SiteSettings, Levels,
    QuestionReport, LearningAssignment, TrainingResultData,
)
from app.views import _assignment_question_ids, _visible_assignments, assignment_status, review_rows
from app.list_filters import filtered_list_url, remember_filters
from app.login_function import apply_remember, post_login_setup, safe_next_url
from .forms import CatalogForm, TheoryQuestionForm, PracticalForm, GroupExerciseForm, ExamForm, WorkForm, WorkCreateForm, ImportQuestionForm, LevelForm, PushMessageForm, LearningAssignmentForm
from .models import PinnedGroup, Profile, PushSubscription
from .utils import pin_group, unpin_group
from .push import push_configured, send_push
import logging
import msal
import requests
import uuid
import secrets
import string
import csv
import json
import io
import os
from django.urls import reverse
from la_tool import env

logger = logging.getLogger(__name__)

# All custom permissions defined across app models (codename, label)
APP_PERMISSIONS = [
    ('access_admin', 'Admin-Bereich zugreifen'),
    ('manage_levels', 'Stufen verwalten'),
    ('manage_catalogs', 'Kataloge verwalten'),
    ('manage_theory', 'Theoriefragen verwalten'),
    ('manage_practical', 'Praktische Aufgaben verwalten'),
    ('manage_group_exercises', 'Gruppenaufgaben verwalten'),
    ('manage_exams', 'Prüfungen verwalten'),
    ('view_exam_results', 'Prüfungsergebnisse einsehen'),
    ('release_exam_results', 'Prüfungsergebnisse freigeben'),
    ('manage_work', 'Dienste verwalten'),
    ('sync_divera_work', 'Dienste aus Divera synchronisieren'),
    ('manage_settings', 'Einstellungen verwalten'),
    ('manage_users', 'Nutzer verwalten'),
    ('manage_groups', 'Gruppen und Berechtigungen verwalten'),
    ('send_notifications', 'Benachrichtigungen senden'),
    ('view_learning_progress', 'Lernstand einsehen'),
    ('manage_assignments', 'Lernaufträge verwalten'),
]


def admin_permission_required(*perms):
    """Decorator für Admin-Seiten: Anmeldung, 'access_admin' und alle übergebenen Rechte nötig.

    Nicht angemeldet -> Login (mit Rücksprung), fehlendes Recht -> 403-Seite mit Begründung.
    """
    required = ('app.access_admin',) + perms

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not request.user.has_perms(required):
                raise PermissionDenied(_missing_permission_text(request.user, required))
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def _missing_permission_text(user, required):
    labels = dict(APP_PERMISSIONS)
    missing = [labels.get(p.split('.', 1)[1], p) for p in required if not user.has_perm(p)]
    return 'Dir fehlt die Berechtigung: ' + ', '.join(missing) + '.'


# Zugriff auf den Admin-Bereich ohne weiteres Einzelrecht
admin_required = admin_permission_required()


def _report_push(request, sent):
    """Rückmeldung an den Admin, wie viele Geräte eine Push-Benachrichtigung erhalten haben."""
    if sent:
        messages.success(request, f'Push-Benachrichtigung an {sent} Gerät{"e" if sent != 1 else ""} gesendet.')
    else:
        messages.info(request, 'Keine Push-Benachrichtigung zugestellt: kein Empfänger hat Push aktiviert.')


def send_divera_notification(user_profile, subject, message):
    """Send a Divera private message to a single user via their UCR ID. Returns True on success."""
    try:
        admin_key = env.DIVERA_ADMIN_USER_API_KEY
        if not admin_key:
            logger.warning('Divera-Nachricht nicht gesendet: kein Admin-API-Key konfiguriert.')
            return False

        ucr_id = user_profile.divera_ucr
        if not ucr_id:
            return False

        payload = {
            'News': {
                'title': subject,
                'text': message,
                'private_mode': True,
                'send_push': True,
                'user_cluster_relation': [ucr_id],
            },
            'instructions': {
                'user_cluster_relation': {'mapping': 'id'},
            },
        }
        # URL enthält den Admin-Key: nie loggen (auch nicht über Exception-Texte)
        resp = requests.post('https://app.divera247.com/api/v2/news', params={'accesskey': admin_key},
                             json=payload, timeout=10)
        if resp.status_code != 200:
            logger.warning('Divera-Nachricht an Nutzer %s fehlgeschlagen: HTTP %s', user_profile.user_id, resp.status_code)
        return resp.status_code == 200
    except Exception as e:
        logger.warning('Divera-Nachricht an Nutzer %s fehlgeschlagen: %s', user_profile.user_id, type(e).__name__)
        return False


@admin_required
def index(request):
    user = request.user
    from django.utils import timezone as tz
    # Namen und Punkte Minderjähriger nur für Personen mit Recht „Prüfungsergebnisse einsehen“
    recent_results = (ExamResultData.objects.select_related('user', 'exam').order_by('-meta_time')[:5]
                      if user.has_perm('app.view_exam_results') else [])
    unreleased_count = ExamResultData.objects.filter(state='hidden').count()
    total_users = User.objects.filter(is_active=True).count()
    active_exams = Exams.objects.filter(visible=True, archived=False).count()
    upcoming_works = Work.objects.filter(date__gte=tz.now()).order_by('date')[:3]

    return render(request, "admin-home.html", {
        "user": user,
        "recent_results": recent_results,
        "unreleased_count": unreleased_count,
        "total_users": total_users,
        "active_exams": active_exams,
        "upcoming_works": upcoming_works,
        "open_reports": QuestionReport.objects.filter(resolved_at__isnull=True).count(),
    })



def sync_user_groups(user, access_token):
    """Entra-Gruppen des Nutzers abrufen, am Profil merken und die Gruppen abgleichen (siehe sync_idp_groups)."""
    from .utils import sync_idp_groups
    headers = {'Authorization': f'Bearer {access_token}'}
    url = 'https://graph.microsoft.com/v1.0/me/memberOf?$select=id'
    group_ids = []
    try:
        # memberOf ist seitenweise (100 pro Seite): nextLink folgen
        while url:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                logger.warning('Entra-Gruppen konnten nicht abgerufen werden: HTTP %s', response.status_code)
                return  # unvollständig: lieber nichts ändern als Gruppen fälschlich entfernen
            data = response.json()
            group_ids += [item['id'] for item in data.get('value', [])
                          if 'microsoft.graph.group' in item.get('@odata.type', '') and item.get('id')]
            url = data.get('@odata.nextLink')
    except (requests.RequestException, ValueError) as exc:
        logger.warning('Entra-Gruppen konnten nicht abgerufen werden: %s', type(exc).__name__)
        return

    Profile.objects.filter(user=user).update(entra_group_ids=group_ids)
    try:
        sync_idp_groups(user)
    except Exception:
        logger.exception('Fehler beim Gruppenabgleich für %s', user.username)

# Microsoft OAuth Callbacks


def _entra_refusal(claims, user_info):
    """Fehlertext, wenn das Microsoft-Konto nicht anmelden darf; sonst None.

    Nur Konten des eigenen Tenants und keine Gastkonten (#EXT#): deren Mail-Attribut könnte die Adresse
    eines bestehenden LA-Tool-Kontos tragen und es so übernehmen.
    """
    tenant = (settings.MICROSOFT_AUTH_TENANT_ID or '').lower()
    if tenant and tenant not in ('common', 'organizations', 'consumers') and (claims.get('tid') or '').lower() != tenant:
        logger.warning('Entra-Login abgelehnt: fremder Tenant %s', claims.get('tid'))
        return 'Dieses Microsoft-Konto gehört nicht zur THW-Jugend Gelsenkirchen.'
    if '#EXT#' in (user_info.get('userPrincipalName') or '').upper():
        logger.warning('Entra-Login abgelehnt: Gastkonto %s', user_info.get('userPrincipalName'))
        return 'Gastkonten können sich nicht anmelden. Bitte an einen Admin wenden.'
    return None


def _entra_user(microsoft_id, email, first_name, last_name):
    """Konto zum Microsoft-Login: zuerst über die feste Entra-ID, sonst über die Mail (ohne Groß/klein)."""
    if microsoft_id:
        profile = Profile.objects.select_related('user').filter(entra_oid=microsoft_id).first()
        if profile:
            return profile.user
    user = User.objects.filter(username__iexact=email).first()
    if user is None:
        user = User.objects.create(username=email, email=email, first_name=first_name, last_name=last_name)
    return user


# Nur das eigene Profil und die eigenen Gruppen-IDs (/me/memberOf liefert mit User.Read id und Typ)
ENTRA_SCOPES = ['User.Read']


def _msal_client():
    return msal.ConfidentialClientApplication(
        settings.MICROSOFT_AUTH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_AUTH_TENANT_ID}",
        client_credential=settings.MICROSOFT_AUTH_CLIENT_SECRET,
    )


def microsoft_login(request):
    """Startet den OAuth-Login bei Microsoft Entra ID (Authorization Code mit PKCE, State und Nonce)."""
    if request.user.is_authenticated:
        return redirect('home')

    # msal erzeugt State, Nonce und PKCE-Verifier; der Flow bleibt in der Sitzung bis zum Callback
    flow = _msal_client().initiate_auth_code_flow(ENTRA_SCOPES, redirect_uri=settings.MICROSOFT_AUTH_REDIRECT_URI)
    request.session['entra_flow'] = flow
    request.session['login_next'] = safe_next_url(request, request.GET.get('next'))
    # „Angemeldet bleiben“ vom Login-Formular (ohne Angabe: ja, wie vorausgewählt)
    request.session['login_remember'] = request.GET.get('remember', '1') == '1'
    return redirect(flow['auth_uri'])


def microsoft_callback(request):
    """Verarbeitet den OAuth Callback von Microsoft Entra ID"""
    flow = request.session.pop('entra_flow', None)
    if not flow or request.GET.get('state') != flow.get('state'):
        return render(request, 'login.html', {'error': 'Sicherheitsfehler: State stimmt nicht überein'})

    error = request.GET.get('error')
    if error:
        return render(request, 'login.html', {
            'error': f'Microsoft Login fehlgeschlagen: {request.GET.get("error_description", "")}'
        })
    if not request.GET.get('code'):
        return render(request, 'login.html', {'error': 'Kein Authorization Code erhalten'})

    try:
        # Prüft State, Nonce und PKCE und tauscht den Code gegen Tokens
        token_result = _msal_client().acquire_token_by_auth_code_flow(flow, request.GET.dict())

        if 'error' in token_result:
            return render(request, 'login.html', {
                'error': f'Token-Fehler: {token_result.get("error_description", "Unbekannter Fehler")}'
            })

        # Access Token aus Antwort holen
        access_token = token_result.get('access_token')

        # Microsoft Graph API aufrufen um Benutzerinformationen zu holen
        headers = {'Authorization': f'Bearer {access_token}'}
        graph_response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers=headers,
            timeout=10,
        )

        if graph_response.status_code != 200:
            return render(request, 'login.html', {
                'error': 'Fehler beim Abrufen der Benutzerinformationen'
            })

        user_info = graph_response.json()

        # Benutzer-Identifikation
        microsoft_id = user_info.get('id')
        email = user_info.get('mail') or user_info.get('userPrincipalName')
        first_name = user_info.get('givenName', '')
        # Default-Wert wenn leer
        last_name = user_info.get('surname', '') or 'User'

        if not email:
            return render(request, 'login.html', {
                'error': 'E-Mail-Adresse konnte nicht abgerufen werden'
            })

        refusal = _entra_refusal(token_result.get('id_token_claims') or {}, user_info)
        if refusal:
            return render(request, 'login.html', {'error': refusal})

        user = _entra_user(microsoft_id, email, first_name, last_name)
        profile, _ = Profile.objects.get_or_create(user=user)
        # Gleiche Mail, anderes Entra-Konto: nicht übernehmen
        if profile.entra_oid and microsoft_id and profile.entra_oid != microsoft_id:
            logger.warning('Entra-Login abgelehnt: Konto %s gehört zu einer anderen Entra-ID', user.username)
            return render(request, 'login.html', {
                'error': 'Dieses Konto ist mit einem anderen Microsoft-Konto verknüpft. Bitte an einen Admin wenden.'
            })
        if not user.is_active:
            return render(request, 'login.html', {'error': 'Dieses Konto ist deaktiviert.'})
        profile.entra_oid = microsoft_id or profile.entra_oid
        # Divera-Konten bleiben Divera-Konten (Passwort-Login weiter gegen Divera prüfen)
        if profile.login_source != Profile.SOURCE_DIVERA:
            profile.login_source = Profile.SOURCE_ENTRA
        profile.save()

        # Gruppenmitgliedschaften synchronisieren
        sync_user_groups(user, access_token)

        # Benutzer einloggen
        remember = request.session.pop('login_remember', True)
        auth.login(request, user,
                   backend='django.contrib.auth.backends.ModelBackend')
        apply_remember(request, remember)
        post_login_setup(request, user)

        return redirect(request.session.pop('login_next', None) or 'home')

    except Exception:
        logger.exception('Microsoft-Login fehlgeschlagen')
        return render(request, 'login.html', {
            'error': 'Die Anmeldung mit Microsoft ist fehlgeschlagen. Bitte erneut versuchen.'
        })

# ── NUTZERVERWALTUNG ─────────────────────────────────────────────────────────

def target_name(user):
    return user.get_full_name() or user.username


@admin_permission_required('app.manage_users')
def admin_users(request):
    admin_group = Group.objects.filter(name='LA-Tool-Admins').first()

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')
        target = get_object_or_404(User, pk=user_id)

        # Rechte vergeben/entziehen und Eingriffe in Admin-Konten (Passwort, Löschen) nur mit
        # 'manage_groups' – sonst könnte 'manage_users' sich über Dritte Rechte verschaffen.
        needs_group_perm = action in ('make_admin', 'remove_admin', 'toggle_perm', 'pin_group', 'unpin_group',
                                      'add_group', 'remove_group') or (
            action in ('reset_password', 'delete_user') and target.has_perm('app.access_admin')
        )
        if needs_group_perm and not request.user.has_perm('app.manage_groups'):
            raise PermissionDenied(_missing_permission_text(request.user, ('app.manage_groups',)))

        if not target.is_superuser and target.pk != request.user.pk:
            if action == 'make_admin':
                # Manuell vergeben = festgesetzt: der IdP-Abgleich entfernt die Admin-Gruppe nicht mehr
                group, _ = Group.objects.get_or_create(name='LA-Tool-Admins')
                pin_group(target, group, by=request.user)
                target.is_staff = True
                target.save()
                messages.success(request, f'{target_name(target)} ist jetzt Admin.')
            elif action == 'remove_admin':
                if admin_group:
                    unpin_group(target, admin_group, remove=True)
                target.is_staff = False
                target.save()
                messages.success(request, f'{target_name(target)} ist kein Admin mehr.')
            elif action in ('pin_group', 'unpin_group', 'add_group', 'remove_group'):
                group = get_object_or_404(Group, pk=request.POST.get('group_id'))
                if action in ('pin_group', 'add_group'):
                    pin_group(target, group, by=request.user)
                else:
                    unpin_group(target, group, remove=(action == 'remove_group'))
                messages.success(request, {
                    'pin_group': f'Gruppe „{group.name}“ für {target_name(target)} festgesetzt.',
                    'add_group': f'{target_name(target)} zur Gruppe „{group.name}“ hinzugefügt.',
                    'unpin_group': f'Gruppe „{group.name}“ für {target_name(target)} gelöst.',
                    'remove_group': f'{target_name(target)} aus der Gruppe „{group.name}“ entfernt.',
                }[action])
            elif action == 'reset_password' and not target.has_usable_password():
                messages.warning(request, f'{target_name(target)} meldet sich über Divera oder Microsoft an und hat kein lokales Passwort.')
            elif action == 'reset_password':
                alphabet = string.ascii_letters + string.digits + '!@#$%&*'
                pw = ''.join(secrets.choice(alphabet) for _ in range(12))
                target.set_password(pw)
                target.save()
                request.session['temp_pw_info'] = {
                    'name': target.get_full_name() or target.username,
                    'password': pw,
                }
            elif action == 'delete_user':
                name = target_name(target)
                target.delete()
                messages.success(request, f'Konto {name} gelöscht.')
            elif action == 'toggle_perm':
                perm_codename = request.POST.get('perm_codename', '')
                if perm_codename in [c for c, _ in APP_PERMISSIONS]:
                    try:
                        perm = Permission.objects.get(codename=perm_codename, content_type__app_label='app')
                        has_direct = target.user_permissions.filter(pk=perm.pk).exists()
                        if has_direct:
                            target.user_permissions.remove(perm)
                        else:
                            target.user_permissions.add(perm)
                        label = dict(APP_PERMISSIONS)[perm_codename]
                        messages.success(request, f'„{label}“ für {target_name(target)} '
                                                  + ('entzogen.' if has_direct else 'vergeben.'))
                        # Clear Django's per-instance permission cache so the next
                        # request reflects the change immediately
                        for attr in ('_perm_cache', '_user_perm_cache'):
                            if hasattr(target, attr):
                                delattr(target, attr)
                    except Permission.DoesNotExist:
                        pass

        # Zurück zur bearbeiteten Person (aufgeklapptes Rechte-Feld bleibt offen)
        if action == 'delete_user':
            return redirect('admin_users')
        return redirect(f"{reverse('admin_users')}?offen={target.pk}#user-{target.pk}")

    temp_pw_info = request.session.pop('temp_pw_info', None)

    from django.db.models import Subquery, CharField
    login_source_sq = Subquery(
        Profile.objects.filter(user_id=OuterRef('pk')).values('login_source')[:1],
        output_field=CharField(),
    )
    base_qs = User.objects.annotate(login_source=login_source_sq)

    if admin_group:
        users = base_qs.annotate(
            is_la_admin=Exists(
                User.groups.through.objects.filter(
                    user_id=OuterRef('pk'),
                    group_id=admin_group.pk,
                )
            )
        ).order_by('last_name', 'first_name')
    else:
        users = base_qs.order_by('last_name', 'first_name')
    # Rechte einmal vorladen (vorher 3 Abfragen je Person über has_perm)
    app_perms = Permission.objects.filter(content_type__app_label='app').only('codename')
    users = users.prefetch_related(
        Prefetch('user_permissions', queryset=app_perms, to_attr='app_perms'),
        Prefetch('groups', queryset=Group.objects.prefetch_related(
            Prefetch('permissions', queryset=app_perms, to_attr='app_perms'))),
    )

    # Je Person: direkte Rechte und über Gruppen geerbte (für den richtigen Knopfzustand)
    all_codes = {c for c, _ in APP_PERMISSIONS}
    users_list = list(users)
    for u in users_list:
        u.la_perms_direct = {p.codename for p in u.app_perms}
        if u.is_superuser:
            inherited = all_codes
        elif u.is_active:  # wie has_perm: gesperrte Konten erben nichts
            inherited = {p.codename for g in u.groups.all() for p in g.app_perms}
        else:
            inherited = set()
        u.la_perms_group = (inherited & all_codes) - u.la_perms_direct
        u.has_admin_access = u.is_superuser or 'access_admin' in u.la_perms_direct | u.la_perms_group

    pinned = {}
    for user_id, group_id in PinnedGroup.objects.values_list('user_id', 'group_id'):
        pinned.setdefault(user_id, set()).add(group_id)
    for u in users_list:
        u.pinned_group_ids = pinned.get(u.pk, set())
        u.member_group_ids = {g.pk for g in u.groups.all()}

    return render(request, 'admin-users.html', {
        'user': request.user,
        'users': users_list,
        'all_groups': Group.objects.order_by('name'),
        'admin_group': admin_group,
        'temp_pw_info': temp_pw_info,
        'app_permissions': APP_PERMISSIONS,
        'open_user': int(request.GET['offen']) if request.GET.get('offen', '').isdigit() else None,
    })


# ── ENTWURF-TOGGLE ───────────────────────────────────────────────────────────

@admin_required
def admin_draft_toggle(request, model, pk):
    if request.method != 'POST':
        return redirect('admin_index')
    perm_map = {
        'level': 'manage_levels',
        'catalog': 'manage_catalogs',
        'theory': 'manage_theory',
        'practical': 'manage_practical',
        'group': 'manage_group_exercises',
        'work': 'manage_work',
    }
    required_perm = perm_map.get(model)
    if required_perm and not request.user.has_perm(f'app.{required_perm}'):
        raise PermissionDenied(_missing_permission_text(request.user, (f'app.{required_perm}',)))
    model_map = {
        'level': Levels,
        'catalog': Questions_Catalogs,
        'theory': Questions_Theory,
        'practical': Questions_Practical,
        'group': Questions_GroupExercise,
        'work': Work,
    }
    redirect_map = {
        'level': 'admin_level_list',
        'catalog': 'admin_catalog',
        'theory': 'admin_catalog',
        'practical': 'admin_catalog',
        'group': 'admin_group_list',
        'work': 'admin_work_list',
    }
    ModelClass = model_map.get(model)
    if not ModelClass:
        return redirect('admin_index')
    obj = get_object_or_404(ModelClass, pk=pk)
    obj.is_draft = not obj.is_draft
    obj.save(update_fields=['is_draft'])
    return redirect(filtered_list_url(request, redirect_map.get(model, 'admin_index')))


# ── FRAGENKATALOG: KATALOGE ───────────────────────────────────────────────────

def _list_filters(request, *names):
    """Filterwerte aus der URL (GET), leer = kein Filter."""
    return {name: request.GET.get(name, '').strip() for name in names}


def _filter_by_level(qs, stufe, none_value):
    """stufe: Slug einer Stufe, none_value (= ohne Stufe) oder leer (alle)."""
    if stufe == none_value:
        return qs.filter(level__isnull=True)
    if stufe:
        return qs.filter(level__slug=stufe)
    return qs


def _filter_by_status(qs, status):
    if status == 'live':
        return qs.filter(is_draft=False)
    if status == 'draft':
        return qs.filter(is_draft=True)
    return qs


@admin_required
def admin_catalog_list(request):
    filters = _list_filters(request, 'q', 'stufe', 'status', 'inhalt')
    remember_filters(request, 'admin_catalog')
    all_catalogs = Questions_Catalogs.objects.select_related('level').order_by('level__order', 'order', 'title')
    qs = _filter_by_status(_filter_by_level(all_catalogs, filters['stufe'], 'ohne'), filters['status'])
    if filters['q']:
        qs = qs.filter(Q(title__icontains=filters['q']) | Q(short_title__icontains=filters['q']))
    catalogs = list(qs)
    # Je Fragenart eine gruppierte Zählung statt zwei Queries pro Katalog
    counts = {
        attr: dict(model.objects.order_by().values_list('catalog').annotate(n=Count('pk')))
        for attr, model in (('n_theory', Questions_Theory), ('n_practical', Questions_Practical))
    }
    for c in catalogs:
        for attr, by_catalog in counts.items():
            setattr(c, attr, by_catalog.get(c.pk, 0))
    content_filters = {
        'ohne_theorie': lambda c: not c.n_theory,
        'ohne_praxis': lambda c: not c.n_practical,
        'leer': lambda c: not c.n_theory and not c.n_practical,
    }
    if filters['inhalt'] in content_filters:
        catalogs = [c for c in catalogs if content_filters[filters['inhalt']](c)]
    return render(request, 'admin-catalog.html', {
        'user': request.user,
        'catalogs': catalogs,
        'total': all_catalogs.count(),
        'filters': filters,
        'filtered': any(filters.values()),
        'levels': Levels.objects.order_by('order'),
    })


@admin_permission_required('app.manage_catalogs')
def admin_catalog_create(request):
    form = CatalogForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect(filtered_list_url(request, 'admin_catalog'))
    return render(request, 'admin-catalog-create.html', {
        'user': request.user,
        'form': form,
        'title': 'Neuer Katalog',
    })


@admin_required
def admin_catalog_detail(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    form = CatalogForm(instance=catalog)
    theory_qs = Questions_Theory.objects.filter(catalog=catalog).order_by('number', 'pk')
    practical_qs = Questions_Practical.objects.filter(catalog=catalog).order_by('number', 'pk')
    return render(request, 'admin-catalog-detail.html', {
        'user': request.user,
        'catalog': catalog,
        'form': form,
        'theory_questions': theory_qs,
        'practical_questions': practical_qs,
        'active_tab': request.GET.get('tab', 'theory'),
        'move_targets': Questions_Catalogs.objects.exclude(pk=catalog.pk).select_related('level')
                        .order_by('level__order', 'order', 'title'),
    })


@admin_permission_required('app.manage_catalogs')
def admin_catalog_update(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        form = CatalogForm(request.POST, request.FILES, instance=catalog)
        if form.is_valid():
            form.save()
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


@admin_permission_required('app.manage_catalogs')
def admin_catalog_delete(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        catalog.delete()
        messages.success(request, f'Katalog „{catalog.title}“ gelöscht.')
        return redirect(filtered_list_url(request, 'admin_catalog'))
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── THEORIEFRAGEN ─────────────────────────────────────────────────────────────

@admin_permission_required('app.manage_theory')
def admin_theory_create(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        form = TheoryQuestionForm(request.POST)
        if form.is_valid():
            choices, correct_texts = TheoryQuestionForm.parse_choices_from_post(request.POST)
            if len(choices) < 2:
                form.add_error(None, 'Mindestens 2 Antwortoptionen erforderlich.')
            elif not correct_texts:
                form.add_error(None, 'Mindestens eine richtige Antwort muss markiert sein.')
            else:
                form.save_to_model(catalog, choices, correct_texts)
                return redirect('admin_catalog_detail', catalog_id=catalog_id)
    else:
        form = TheoryQuestionForm()
    is_post = request.method == 'POST'
    return render(request, 'admin-question-theory.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'init_choices': [c.strip() for c in request.POST.getlist('choice')] if is_post else ['', '', '', ''],
        'init_correct': request.POST.getlist('correct') if is_post else [],
        'title': 'Neue Theoriefrage',
    })


@admin_permission_required('app.manage_theory')
def admin_theory_edit(request, catalog_id, q_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    question = get_object_or_404(Questions_Theory, pk=q_id, catalog=catalog)
    if request.method == 'POST':
        form = TheoryQuestionForm(request.POST)
        if form.is_valid():
            choices, correct_texts = TheoryQuestionForm.parse_choices_from_post(request.POST)
            if len(choices) < 2:
                form.add_error(None, 'Mindestens 2 Antwortoptionen erforderlich.')
            elif not correct_texts:
                form.add_error(None, 'Mindestens eine richtige Antwort muss markiert sein.')
            else:
                form.save_to_model(catalog, choices, correct_texts, instance=question)
                return redirect('admin_catalog_detail', catalog_id=catalog_id)
        init_choices = [c.strip() for c in request.POST.getlist('choice')]
        init_correct = request.POST.getlist('correct')
    else:
        form = TheoryQuestionForm(initial={
            'number': question.number,
            'question': question.question,
            'help_reference': question.help_reference,
        })
        init_choices = question.answer_choice or ['', '', '', '']
        correct_set = set(question.correct_answers)
        init_correct = [str(i) for i, c in enumerate(init_choices) if c in correct_set]
    return render(request, 'admin-question-theory.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'question': question,
        'init_choices': init_choices,
        'init_correct': init_correct,
        'title': 'Theoriefrage bearbeiten',
    })


@admin_permission_required('app.manage_theory')
def admin_theory_delete(request, catalog_id, q_id):
    question = get_object_or_404(Questions_Theory, pk=q_id, catalog_id=catalog_id)
    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Theoriefrage gelöscht.')
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── SAMMELAKTIONEN IM KATALOG ─────────────────────────────────────────────────

BULK_KINDS = {
    # Art: (Modell, Recht, Einzahl, Mehrzahl)
    'theory': (Questions_Theory, 'manage_theory', 'Frage', 'Fragen'),
    'practical': (Questions_Practical, 'manage_practical', 'Aufgabe', 'Aufgaben'),
}


@admin_required
def admin_catalog_bulk(request, catalog_id):
    """Mehrere Fragen/Aufgaben eines Katalogs auf einmal freigeben, zurückstellen, verschieben oder löschen."""
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    kind = request.POST.get('kind', '')
    if kind not in BULK_KINDS:
        raise Http404
    model, perm, one, many = BULK_KINDS[kind]
    if request.method != 'POST':
        return redirect('admin_catalog_detail', catalog_id=catalog.pk)
    if not request.user.has_perm(f'app.{perm}'):
        raise PermissionDenied(_missing_permission_text(request.user, (f'app.{perm}',)))

    ids = [int(x) for x in request.POST.getlist('ids') if x.isdigit()]
    items = model.objects.filter(catalog=catalog, pk__in=ids)
    count = items.count()
    noun = one if count == 1 else many
    action = request.POST.get('action')
    if not count:
        messages.warning(request, f'Keine {many} ausgewählt.')
    elif action == 'publish':
        items.update(is_draft=False)
        messages.success(request, f'{count} {noun} freigegeben.')
    elif action == 'draft':
        items.update(is_draft=True)
        messages.success(request, f'{count} {noun} als Entwurf markiert.')
    elif action == 'move':
        target = Questions_Catalogs.objects.filter(pk=request.POST.get('target')).exclude(pk=catalog.pk).first()
        if target is None:
            messages.warning(request, 'Bitte einen Ziel-Katalog wählen.')
        else:
            numbers = {n for n in items.values_list('number', flat=True) if n}
            clashes = model.objects.filter(catalog=target, number__in=numbers).count()
            items.update(catalog=target)
            text = f'{count} {noun} nach „{target}“ verschoben.'
            if clashes:
                text += f' Achtung: {clashes} Nummer{"n" if clashes != 1 else ""} gibt es dort schon doppelt.'
            messages.success(request, text)
    elif action == 'delete':
        with transaction.atomic():
            for item in items:
                item.delete()  # einzeln, damit Signale (z.B. Dateien löschen) greifen
        messages.success(request, f'{count} {noun} gelöscht.')
    return redirect('admin_catalog_detail', catalog_id=catalog.pk)


# ── IMPORT ────────────────────────────────────────────────────────────────────

def _is_truthy(val):
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 'ja', 'yes', 'x', 'wahr')


# Obergrenzen für den Fragen-Import (Schutz vor versehentlich riesigen Dateien)
IMPORT_MAX_BYTES = 5 * 1024 * 1024
IMPORT_MAX_ROWS = 2000


def _parse_import_file(file_obj, filename):
    """Parse uploaded XLSX, CSV, or JSON file. Returns list of dicts:
    number, question, choices (list), correct (list of texts), help.

    Primary format (XLSX/CSV): Nr | Frage | A | B | C | Lösung A | Lösung B | Lösung C | Hinweis
    JSON format: [{"number":..., "question":..., "choices":[...], "correct":[...], "help":...}]
    """
    raw = file_obj.read()
    fn = filename.lower()

    if fn.endswith('.json'):
        data = json.loads(raw.decode('utf-8-sig'))
        rows = []
        for item in data:
            choices = item.get('choices') or item.get('answers') or []
            correct_raw = item.get('correct') or item.get('korrekt') or []
            correct_texts = []
            for c in (correct_raw if isinstance(correct_raw, list) else [correct_raw]):
                if isinstance(c, int):
                    if 0 <= c < len(choices):
                        correct_texts.append(choices[c])
                else:
                    correct_texts.append(str(c))
            rows.append({
                'number': str(item.get('number') or item.get('nummer') or '').strip(),
                'question': str(item.get('question') or item.get('frage') or '').strip(),
                'choices': [str(x).strip() for x in choices if str(x).strip()],
                'correct': correct_texts,
                'help': str(item.get('help') or item.get('hinweis') or '').strip(),
            })
        return rows

    elif fn.endswith('.xlsx'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True, read_only=True)
        ws = wb.active
        header_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
        if not header_row:
            return []
        headers = [str(h or '').strip() for h in header_row]
        col_idx = {h: i for i, h in enumerate(headers) if h}

        # Answer text columns: single uppercase letter (A, B, C, D…)
        answer_letters = [h for h in headers if len(h) == 1 and h.isalpha() and h.isupper()]

        # Solution columns: "Lösung A", "Loesung B" etc. → letter → col index
        solution_map = {}
        for h in headers:
            h_lower = h.lower()
            if 'l' in h_lower and ('sung' in h_lower):
                parts = h.split()
                if len(parts) >= 2:
                    letter = parts[-1].upper()
                    if len(letter) == 1 and letter.isalpha() and h in col_idx:
                        solution_map[letter] = col_idx[h]

        rows = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not any(row):
                continue
            number_col = next((k for k in ('Nr', 'Nummer', 'nummer', 'number') if k in col_idx), None)
            number = str(row[col_idx[number_col]] or '').strip() if number_col else ''
            question_col = next((k for k in ('Frage', 'frage', 'Question', 'question') if k in col_idx), None)
            question = str(row[col_idx[question_col]] or '').strip() if question_col else ''

            choice_map = {}
            for letter in answer_letters:
                val = row[col_idx[letter]] if letter in col_idx else None
                if val is not None and str(val).strip():
                    choice_map[letter] = str(val).strip()
            choices = [choice_map[l] for l in answer_letters if l in choice_map]

            correct_texts = []
            for letter, sol_idx in solution_map.items():
                val = row[sol_idx] if sol_idx < len(row) else None
                if _is_truthy(val) and letter in choice_map:
                    correct_texts.append(choice_map[letter])

            help_col = next((k for k in ('Hinweis', 'hinweis', 'Help', 'help') if k in col_idx), None)
            help_text = str(row[col_idx[help_col]] or '').strip() if help_col else ''

            if question or number:
                rows.append({
                    'number': number,
                    'question': question,
                    'choices': choices,
                    'correct': correct_texts,
                    'help': help_text,
                })
        return rows

    else:
        # CSV: semicolon-separated
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text), delimiter=';')
        rows = []
        for row in reader:
            keys = list(row.keys())
            answer_letters = [k.strip() for k in keys if len(k.strip()) == 1 and k.strip().isalpha() and k.strip().isupper()]

            if answer_letters:
                # New format: A, B, C columns + "Lösung A" etc.
                choice_map = {}
                for letter in answer_letters:
                    val = row.get(letter, '').strip()
                    if val:
                        choice_map[letter] = val
                choices = [choice_map[l] for l in answer_letters if l in choice_map]

                correct_texts = []
                for key in keys:
                    k_lower = key.strip().lower()
                    if 'l' in k_lower and 'sung' in k_lower:
                        parts = key.strip().split()
                        if len(parts) >= 2:
                            letter = parts[-1].upper()
                            if _is_truthy(row.get(key, '')) and letter in choice_map:
                                correct_texts.append(choice_map[letter])
            else:
                # Legacy format: Antwort_1, Antwort_2 + Korrekt (pipe-separated)
                choices = []
                for key in keys:
                    k = key.strip().lower()
                    if k.startswith('antwort') or k.startswith('choice') or k.startswith('answer'):
                        val = row[key].strip()
                        if val:
                            choices.append(val)
                korrekt_raw = row.get('Korrekt') or row.get('korrekt') or row.get('correct') or ''
                correct_texts = [c.strip() for c in korrekt_raw.split('|') if c.strip()]

            number_key = next((k for k in ('Nr', 'Nummer', 'nummer', 'number') if k in row), None)
            question_key = next((k for k in ('Frage', 'frage', 'question') if k in row), None)
            help_key = next((k for k in ('Hinweis', 'hinweis', 'help') if k in row), None)
            rows.append({
                'number': row.get(number_key, '').strip() if number_key else '',
                'question': row.get(question_key, '').strip() if question_key else '',
                'choices': choices,
                'correct': correct_texts,
                'help': row.get(help_key, '').strip() if help_key else '',
            })
        return rows


@admin_permission_required('app.manage_theory')
def admin_import_questions(request):
    catalog_id = request.GET.get('catalog')
    initial = {}
    if catalog_id:
        try:
            initial['catalog'] = Questions_Catalogs.objects.get(pk=catalog_id)
        except Questions_Catalogs.DoesNotExist:
            pass
    form = ImportQuestionForm(initial=initial)
    results = None

    if request.method == 'POST':
        form = ImportQuestionForm(request.POST, request.FILES)
        if form.is_valid():
            catalog = form.cleaned_data['catalog']
            update_existing = form.cleaned_data.get('update_existing', True)
            uploaded = request.FILES['file']

            rows = []
            if uploaded.size > IMPORT_MAX_BYTES:
                form.add_error('file', f'Datei ist zu groß (höchstens {IMPORT_MAX_BYTES // (1024 * 1024)} MB).')
            else:
                try:
                    rows = _parse_import_file(uploaded, uploaded.name)
                except Exception as e:
                    form.add_error('file', f'Datei konnte nicht gelesen werden: {e}')
            if len(rows) > IMPORT_MAX_ROWS:
                form.add_error('file', f'Zu viele Zeilen ({len(rows)}); höchstens {IMPORT_MAX_ROWS} pro Import.')
                rows = []

            created = updated = skipped = 0
            errors = []

            # Alles oder nichts: bricht der Import mittendrin ab, bleibt der Katalog unverändert
            with transaction.atomic():
                for i, row in enumerate(rows, start=1):
                    if not row['question']:
                        errors.append(f'Zeile {i}: Fragetext fehlt.')
                        skipped += 1
                        continue
                    if len(row['choices']) < 2:
                        errors.append(f'Zeile {i} ({row["number"] or "?"}): Weniger als 2 Antwortoptionen.')
                        skipped += 1
                        continue
                    if not row['correct']:
                        errors.append(f'Zeile {i} ({row["number"] or "?"}): Keine korrekte Antwort angegeben.')
                        skipped += 1
                        continue

                    existing = None
                    if update_existing and row['number']:
                        existing = Questions_Theory.objects.filter(
                            catalog=catalog, number=row['number']
                        ).first()

                    if existing and update_existing:
                        existing.question = row['question']
                        existing.answer_choice = row['choices']
                        existing.answer_correct = row['correct']
                        existing.answer_text = row['correct'][0]
                        existing.help_reference = row['help']
                        existing.save()
                        updated += 1
                    else:
                        Questions_Theory.objects.create(
                            catalog=catalog,
                            number=row['number'],
                            question=row['question'],
                            answer_choice=row['choices'],
                            answer_correct=row['correct'],
                            answer_text=row['correct'][0],
                            help_reference=row['help'],
                        )
                        created += 1

            results = {
                'created': created,
                'updated': updated,
                'skipped': skipped,
                'errors': errors,
                'catalog': catalog,
            }

    return render(request, 'admin-import-questions.html', {
        'user': request.user,
        'form': form,
        'results': results,
    })


@admin_permission_required('app.manage_theory')
def admin_import_example(request, fmt):
    if fmt == 'xlsx':
        try:
            import openpyxl
        except ImportError:
            return HttpResponse('openpyxl nicht installiert. Bitte "pip install openpyxl" ausführen.', status=500)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Fragen'
        ws.append(['Nr', 'Frage', 'A', 'B', 'C', 'Lösung A', 'Lösung B', 'Lösung C', 'Hinweis'])
        ws.append(['S-1-01', 'Was ist THW?', 'Technisches Hilfswerk', 'Deutsches Hilfswerk', 'Bundeswehr', True, False, False, 'Grundlagen'])
        ws.append(['S-1-02', 'Welche Farbe hat das THW-Logo?', 'Blau', 'Rot', 'Grün', True, False, False, ''])
        ws.append(['S-1-03', 'Was kann korrekt sein?', 'Antwort A', 'Antwort B', 'Antwort C', True, True, False, 'Mehrere korrekt'])
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="fragen_beispiel.xlsx"'
        return response

    elif fmt == 'csv':
        lines = [
            'Nr;Frage;A;B;C;Lösung A;Lösung B;Lösung C;Hinweis',
            'S-1-01;Was ist THW?;Technisches Hilfswerk;Deutsches Hilfswerk;Bundeswehr;Ja;Nein;Nein;Grundlagen',
            'S-1-02;Welche Farbe hat das THW-Logo?;Blau;Rot;Grün;Ja;Nein;Nein;',
            'S-1-03;Was kann korrekt sein?;Antwort A;Antwort B;Antwort C;Ja;Ja;Nein;Mehrere korrekt',
        ]
        content = ('\r\n'.join(lines) + '\r\n').encode('utf-8')
        response = HttpResponse(b'\xef\xbb\xbf' + content, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="fragen_beispiel.csv"'
        return response

    elif fmt == 'json':
        data = [
            {
                'number': 'S-1-01',
                'question': 'Was ist THW?',
                'choices': ['Technisches Hilfswerk', 'Deutsches Hilfswerk', 'Bundeswehr'],
                'correct': ['Technisches Hilfswerk'],
                'help': 'Grundlagen',
            },
            {
                'number': 'S-1-02',
                'question': 'Welche Farbe hat das THW-Logo?',
                'choices': ['Blau', 'Rot', 'Grün'],
                'correct': [0],
            },
            {
                'number': 'S-1-03',
                'question': 'Was kann korrekt sein?',
                'choices': ['Antwort A', 'Antwort B', 'Antwort C'],
                'correct': [0, 1],
                'help': 'Mehrere korrekt',
            },
        ]
        response = HttpResponse(
            json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'),
            content_type='application/json',
        )
        response['Content-Disposition'] = 'attachment; filename="fragen_beispiel.json"'
        return response

    raise Http404


# ── PRAKTISCHE AUFGABEN ───────────────────────────────────────────────────────

@admin_permission_required('app.manage_practical')
def admin_practical_create(request, catalog_id):
    import uuid as _uuid
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        form = PracticalForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES.get('file')
            if uploaded:
                existing = Questions_Practical.objects.filter(
                    file='Aufgaben-Praktisch/' + uploaded.name
                ).first()
                if existing and existing.file:
                    # Duplicate detected → save temp and ask user to choose
                    safe_name = os.path.basename(uploaded.name)
                    temp_path = f'tmp/{_uuid.uuid4().hex}/{safe_name}'
                    default_storage.save(temp_path, ContentFile(uploaded.read()))
                    request.session['pending_file_upload'] = {
                        'model': 'practical',
                        'catalog_id': catalog_id,
                        'temp_path': temp_path,
                        'existing_path': existing.file.name,
                        'form_data': {
                            'number': form.cleaned_data.get('number', ''),
                            'question': form.cleaned_data.get('question', ''),
                            'help_reference': form.cleaned_data.get('help_reference', ''),
                        },
                    }
                    return redirect('admin_file_confirm')
            obj = form.save(commit=False)
            obj.catalog = catalog
            obj.save()
            return redirect('admin_catalog_detail', catalog_id=catalog_id)
    else:
        form = PracticalForm()
    return render(request, 'admin-question-practical.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'title': 'Neue Praktische Aufgabe',
    })


@admin_permission_required('app.manage_practical')
def admin_practical_edit(request, catalog_id, q_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    question = get_object_or_404(Questions_Practical, pk=q_id, catalog=catalog)
    if request.method == 'POST':
        form = PracticalForm(request.POST, request.FILES, instance=question)
        if not request.FILES.get('file'):
            # Exclude file field so save_form_data never re-saves the existing file
            del form.fields['file']
        if form.is_valid():
            form.save()
            return redirect('admin_catalog_detail', catalog_id=catalog_id)
    else:
        form = PracticalForm(instance=question)
    return render(request, 'admin-question-practical.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'question': question,
        'title': 'Praktische Aufgabe bearbeiten',
    })


@admin_permission_required('app.manage_practical')
def admin_practical_delete(request, catalog_id, q_id):
    question = get_object_or_404(Questions_Practical, pk=q_id, catalog_id=catalog_id)
    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Praktische Aufgabe gelöscht.')
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── GRUPPENAUFGABEN ───────────────────────────────────────────────────────────

@admin_permission_required('app.manage_group_exercises')
def admin_group_list(request):
    """Gruppenaufgaben – eigenständig, nach LA-Stufe gruppiert (ohne Stufe = für alle Stufen)."""
    filters = _list_filters(request, 'q', 'stufe', 'status', 'datei')
    remember_filters(request, 'admin_group_list')
    all_exercises = Questions_GroupExercise.objects.select_related('level').order_by('number', 'pk')
    qs = _filter_by_status(_filter_by_level(all_exercises, filters['stufe'], 'alle'), filters['status'])
    if filters['q']:
        qs = qs.filter(Q(number__icontains=filters['q']) | Q(question__icontains=filters['q'])
                       | Q(help_reference__icontains=filters['q']))
    if filters['datei'] == 'mit':
        qs = qs.exclude(file='').exclude(file__isnull=True)
    elif filters['datei'] == 'ohne':
        qs = qs.filter(Q(file='') | Q(file__isnull=True))
    exercises = list(qs)
    by_level = {}
    for exercise in exercises:
        by_level.setdefault(exercise.level, []).append(exercise)
    sections = sorted(by_level.items(), key=lambda pair: (pair[0] is not None, pair[0].order if pair[0] else 0))
    return render(request, 'admin-group-exercises.html', {
        'sections': sections,
        'shown': len(exercises),
        'total': all_exercises.count(),
        'filters': filters,
        'filtered': any(filters.values()),
        'levels': Levels.objects.order_by('order'),
    })


@admin_permission_required('app.manage_group_exercises')
def admin_group_create(request):
    import uuid as _uuid
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    if request.method == 'POST':
        form = GroupExerciseForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES.get('file')
            if uploaded:
                existing = Questions_GroupExercise.objects.filter(
                    file='Aufgaben-Gruppe/' + uploaded.name
                ).first()
                if existing and existing.file:
                    safe_name = os.path.basename(uploaded.name)
                    temp_path = f'tmp/{_uuid.uuid4().hex}/{safe_name}'
                    default_storage.save(temp_path, ContentFile(uploaded.read()))
                    level = form.cleaned_data.get('level')
                    request.session['pending_file_upload'] = {
                        'model': 'group',
                        'catalog_id': None,
                        'temp_path': temp_path,
                        'existing_path': existing.file.name,
                        'form_data': {
                            'number': form.cleaned_data.get('number', ''),
                            'question': form.cleaned_data.get('question', ''),
                            'help_reference': form.cleaned_data.get('help_reference', ''),
                            'is_draft': form.cleaned_data.get('is_draft', False),
                            'level_id': level.pk if level else None,
                        },
                    }
                    return redirect('admin_file_confirm')
            form.save()
            return redirect(filtered_list_url(request, 'admin_group_list'))
    else:
        form = GroupExerciseForm(initial={'level': Levels.objects.filter(slug=request.session.get('la_filter')).first()})
    return render(request, 'admin-question-group.html', {
        'user': request.user,
        'form': form,
        'title': 'Neue Gruppenaufgabe',
    })


@admin_permission_required('app.manage_group_exercises')
def admin_group_edit(request, q_id):
    question = get_object_or_404(Questions_GroupExercise, pk=q_id)
    if request.method == 'POST':
        form = GroupExerciseForm(request.POST, request.FILES, instance=question)
        if not request.FILES.get('file'):
            # Exclude file field so save_form_data never re-saves the existing file
            del form.fields['file']
        if form.is_valid():
            form.save()
            return redirect(filtered_list_url(request, 'admin_group_list'))
    else:
        form = GroupExerciseForm(instance=question)
    return render(request, 'admin-question-group.html', {
        'user': request.user,
        'form': form,
        'question': question,
        'title': 'Gruppenaufgabe bearbeiten',
    })


@admin_permission_required('app.manage_group_exercises')
def admin_group_delete(request, q_id):
    question = get_object_or_404(Questions_GroupExercise, pk=q_id)
    if request.method == 'POST':
        question.delete()
        messages.success(request, 'Gruppenaufgabe gelöscht.')
    return redirect(filtered_list_url(request, 'admin_group_list'))


# ── DATEI-BESTÄTIGUNG BEI DUPLIKATEN ─────────────────────────────────────────

@admin_required
def admin_file_confirm(request):
    import os as _os
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile

    pending = request.session.get('pending_file_upload')
    if not pending:
        return redirect(filtered_list_url(request, 'admin_catalog'))

    catalog_id = pending['catalog_id']
    model = pending['model']
    file_perm = 'manage_practical' if model == 'practical' else 'manage_group_exercises'
    if not request.user.has_perm(f'app.{file_perm}'):
        raise PermissionDenied(_missing_permission_text(request.user, (f'app.{file_perm}',)))
    temp_path = pending['temp_path']
    existing_path = pending['existing_path']
    form_data = pending['form_data']

    if request.method == 'POST':
        choice = request.POST.get('choice')
        request.session.pop('pending_file_upload', None)

        if model == 'practical':
            obj = Questions_Practical(catalog=get_object_or_404(Questions_Catalogs, pk=catalog_id), **form_data)
        else:
            obj = Questions_GroupExercise(**form_data)  # eigenständig, form_data enthält level_id

        if choice == 'existing':
            # Reuse the already-stored file; discard temp
            existing_qs = (Questions_Practical if model == 'practical' else Questions_GroupExercise)
            ref = existing_qs.objects.filter(file=existing_path).first()
            if ref and ref.file:
                obj.file = ref.file
            else:
                # No DB record for the path — assign it directly by path
                obj.file = existing_path
            if default_storage.exists(temp_path):
                default_storage.delete(temp_path)
                # Clean up the temp uuid directory if empty
                temp_dir = _os.path.dirname(temp_path)
                try:
                    default_storage.delete(temp_dir)
                except Exception:
                    pass
        else:
            # Use the new file: overwrite the existing path with new content
            with default_storage.open(temp_path, 'rb') as f:
                new_content = f.read()
            # Overwrite existing file with new content
            if default_storage.exists(existing_path):
                default_storage.delete(existing_path)
            saved_name = default_storage.save(existing_path, ContentFile(new_content))
            obj.file = saved_name
            # Clean up temp
            if default_storage.exists(temp_path):
                default_storage.delete(temp_path)

        obj.save()
        if model == 'practical':
            return redirect('admin_catalog_detail', catalog_id=catalog_id)
        return redirect(filtered_list_url(request, 'admin_group_list'))

    # GET: render confirmation page with previews
    temp_url = default_storage.url(temp_path)
    existing_url = default_storage.url(existing_path)
    filename = _os.path.basename(existing_path)
    back_url = (
        reverse('admin_practical_create', kwargs={'catalog_id': catalog_id})
        if model == 'practical'
        else reverse('admin_group_create')
    )

    return render(request, 'admin-file-confirm.html', {
        'filename': filename,
        'existing_url': existing_url,
        'temp_url': temp_url,
        'model_label': 'Praktische Aufgabe' if model == 'practical' else 'Gruppenaufgabe',
        'form_data': form_data,
        'back_url': back_url,
        'catalog_id': catalog_id,
    })


# ── PRÜFUNGEN ─────────────────────────────────────────────────────────────────

def _compute_exam_score(exam_result):
    """Returns (score, total, is_passed) from an ExamResultData record."""
    meta = exam_result.meta_reference or {}
    score = meta.get('score', 0)
    total = meta.get('total', 0)
    is_passed = meta.get('passed', False)
    return score, total, is_passed


@admin_required
def admin_exam_list(request):
    active_exams = Exams.objects.filter(archived=False).order_by('-pk')
    archived_exams = Exams.objects.filter(archived=True).order_by('-pk')

    # Ergebnisse aller Prüfungen auf einmal zählen (vorher 2 Abfragen je Prüfung)
    counts = {}
    for exam_id, meta in ExamResultData.objects.filter(exam__isnull=False).values_list('exam_id', 'meta_reference'):
        total, passed = counts.get(exam_id, (0, 0))
        counts[exam_id] = (total + 1, passed + bool((meta or {}).get('passed', False)))

    def _annotate(exams_qs):
        result = []
        for exam in exams_qs:
            total_count, passed_count = counts.get(exam.pk, (0, 0))
            result.append({'exam': exam, 'total': total_count, 'passed': passed_count, 'failed': total_count - passed_count})
        return result

    return render(request, 'admin-exams.html', {
        'user': request.user,
        'active_exams': _annotate(active_exams),
        'archived_exams': _annotate(archived_exams),
    })


def _exam_catalog_data():
    """Kataloge mit ihren Theoriefragen für die Fragenauswahl (eine Abfrage für alle Fragen)."""
    catalogs = Questions_Catalogs.objects.select_related('level').prefetch_related(
        Prefetch('questions_theory_set', queryset=Questions_Theory.objects.order_by('number', 'pk'), to_attr='question_list'),
    ).order_by('level__order', 'order', 'title')
    return [{'catalog': c, 'questions': c.question_list} for c in catalogs]


def _posted_ids(request, name):
    return {int(x) for x in request.POST.getlist(name) if x.isdigit()}


@admin_permission_required('app.manage_exams')
def admin_exam_create(request):
    all_users = User.objects.order_by('last_name', 'first_name')
    all_groups = Group.objects.order_by('name')
    form = ExamForm(request.POST or None)

    if request.method == 'POST' and form.is_valid():
        exam = form.save()
        user_ids = [int(x) for x in request.POST.getlist('user_ids') if x.isdigit()]
        group_ids = [int(x) for x in request.POST.getlist('group_ids') if x.isdigit()]
        question_ids = [int(x) for x in request.POST.getlist('question_ids') if x.isdigit()]
        exam.assigned_users.set(User.objects.filter(pk__in=user_ids))
        exam.assigned_groups.set(Group.objects.filter(pk__in=group_ids))
        exam.questions.set(Questions_Theory.objects.filter(pk__in=question_ids))
        # Divera notification on exam assignment (opt-in)
        if request.POST.get('notify_divera'):
            assigned = list(User.objects.filter(pk__in=user_ids))
            for u in assigned:
                try:
                    send_divera_notification(
                        u.profile,
                        subject=f'Neue Prüfung zugewiesen: {exam.name}',
                        message=(
                            f'Hallo {u.first_name or u.username},\n\n'
                            f'dir wurde die Prüfung „{exam.name}" im LA-Tool zugewiesen.'
                        ),
                    )
                except Exception:
                    logger.exception('Divera-Nachricht zur Prüfung %s an %s fehlgeschlagen', exam.pk, u.pk)
        if request.POST.get('notify_push'):
            recipients = User.objects.filter(
                Q(pk__in=user_ids) | Q(groups__pk__in=group_ids)
            ).distinct()
            _report_push(request, send_push(
                recipients,
                title='Neue Prüfung zugewiesen',
                body=f'Dir wurde die Prüfung „{exam.name}" zugewiesen.',
                url=reverse('exam_start', args=[exam.pk]),
            ))
        return redirect('admin_exam_list')

    catalog_data = _exam_catalog_data()

    level_defaults = {
        str(l.pk): {'pass_pct': l.default_exam_pass_pct, 'count': l.default_exam_count}
        for l in Levels.objects.all()
    }

    return render(request, 'admin-exams-edit-create.html', {
        'user': request.user,
        'form': form,
        'catalog_data': catalog_data,
        'all_users': all_users,
        'all_groups': all_groups,
        # Nach einem Formularfehler die getroffene Auswahl behalten
        'selected_user_ids': _posted_ids(request, 'user_ids'),
        'selected_group_ids': _posted_ids(request, 'group_ids'),
        'selected_question_ids': _posted_ids(request, 'question_ids'),
        'level_defaults_json': json.dumps(level_defaults),
        'title': 'Neue Prüfung',
    })


@admin_permission_required('app.manage_exams')
def admin_exam_edit(request, exam_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    all_users = User.objects.order_by('last_name', 'first_name')
    all_groups = Group.objects.order_by('name')

    if request.method == 'POST':
        form = ExamForm(request.POST, instance=exam)
        if form.is_valid():
            form.save()
            user_ids = [int(x) for x in request.POST.getlist('user_ids') if x.isdigit()]
            group_ids = [int(x) for x in request.POST.getlist('group_ids') if x.isdigit()]
            question_ids = [int(x) for x in request.POST.getlist('question_ids') if x.isdigit()]
            exam.assigned_users.set(User.objects.filter(pk__in=user_ids))
            exam.assigned_groups.set(Group.objects.filter(pk__in=group_ids))
            exam.questions.set(Questions_Theory.objects.filter(pk__in=question_ids))
            return redirect('admin_exam_list')
    else:
        form = ExamForm(instance=exam)

    if request.method == 'POST':  # Formularfehler: Auswahl aus dem Formular behalten
        selected_user_ids = _posted_ids(request, 'user_ids')
        selected_group_ids = _posted_ids(request, 'group_ids')
        selected_question_ids = _posted_ids(request, 'question_ids')
    else:
        selected_user_ids = set(exam.assigned_users.values_list('pk', flat=True))
        selected_group_ids = set(exam.assigned_groups.values_list('pk', flat=True))
        selected_question_ids = set(exam.questions.values_list('pk', flat=True))

    catalog_data = _exam_catalog_data()

    level_defaults = {
        str(l.pk): {'pass_pct': l.default_exam_pass_pct, 'count': l.default_exam_count}
        for l in Levels.objects.all()
    }

    return render(request, 'admin-exams-edit-create.html', {
        'user': request.user,
        'form': form,
        'exam': exam,
        'catalog_data': catalog_data,
        'all_users': all_users,
        'all_groups': all_groups,
        'selected_user_ids': selected_user_ids,
        'selected_group_ids': selected_group_ids,
        'selected_question_ids': selected_question_ids,
        'level_defaults_json': json.dumps(level_defaults),
        'title': 'Prüfung bearbeiten',
    })


@admin_permission_required('app.manage_exams')
def admin_exam_delete(request, exam_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    if request.method == 'POST':
        exam.delete()
        messages.success(request, f'Prüfung „{exam.name}“ gelöscht.')
    return redirect('admin_exam_list')


@admin_permission_required('app.manage_exams')
def admin_exam_toggle(request, exam_id, field):
    if request.method != 'POST':
        return redirect('admin_exam_list')
    exam = get_object_or_404(Exams, pk=exam_id)
    if field in ('visible', 'closed', 'archived'):
        setattr(exam, field, not getattr(exam, field))
        exam.save()
        state = {
            'visible': ('sichtbar', 'ausgeblendet'), 'closed': ('gesperrt', 'freigegeben'),
            'archived': ('archiviert', 'aus dem Archiv geholt'),
        }[field][0 if getattr(exam, field) else 1]
        messages.success(request, f'Prüfung „{exam.name}“ {state}.')
    return redirect('admin_exam_list')


@admin_permission_required('app.view_exam_results')
def admin_exam_results(request, exam_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    results = ExamResultData.objects.filter(exam=exam).select_related('user').order_by('-meta_time')
    results_data = []
    for r in results:
        score, total, is_passed = _compute_exam_score(r)
        results_data.append({
            'result': r,
            'score': score,
            'total': total,
            'is_passed': is_passed,
        })
    return render(request, 'admin-exam-summary.html', {
        'user': request.user,
        'exam': exam,
        'results_data': results_data,
    })


@admin_permission_required('app.view_exam_results')
def admin_exam_result_user(request, exam_id, result_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    result = get_object_or_404(ExamResultData, pk=result_id, exam=exam)
    score, total, is_passed = _compute_exam_score(result)

    # Gleiche Auswertung wie für die Teilnehmenden (beliebig viele Antworten, Mehrfachauswahl)
    questions_data = review_rows(result.questions or [], result.answers or {})

    return render(request, 'admin-exam-summary-user.html', {
        'user': request.user,
        'exam': exam,
        'result': result,
        'score': score,
        'total': total,
        'is_passed': is_passed,
        'questions_data': questions_data,
    })


@admin_permission_required('app.release_exam_results')
def admin_exam_result_release(request, exam_id, result_id):
    if request.method != 'POST':
        return redirect('admin_exam_results', exam_id=exam_id)
    result = get_object_or_404(ExamResultData, pk=result_id, exam_id=exam_id)
    was_hidden = result.state != 'published'
    result.state = 'hidden' if result.state == 'published' else 'published'
    result.save()
    # Divera notification on release (opt-in)
    if was_hidden and result.state == 'published' and request.POST.get('notify_divera'):
        if result.user:
            try:
                profile = result.user.profile
                send_divera_notification(
                    profile,
                    subject=f'Prüfungsergebnis freigegeben: {result.exam.name if result.exam else result.name}',
                    message=(
                        f'Hallo {result.user.first_name or result.user.username},\n\n'
                        f'dein Ergebnis für die Prüfung „{result.exam.name if result.exam else result.name}" '
                        f'wurde freigegeben. Du kannst es jetzt im LA-Tool einsehen.'
                    ),
                )
            except Exception:
                pass
    if was_hidden and result.state == 'published' and request.POST.get('notify_push') and result.user:
        exam_name = result.exam.name if result.exam else result.name
        _report_push(request, send_push(
            [result.user],
            title='Prüfungsergebnis freigegeben',
            body=f'Dein Ergebnis für „{exam_name}" ist freigegeben.',
            url=reverse('exam_result', args=[exam_id]),
        ))
    return redirect('admin_exam_result_user', exam_id=exam_id, result_id=result_id)


# ── DIENSTE ───────────────────────────────────────────────────────────────────

@admin_required
def admin_work_list(request):
    works = Work.objects.select_related('level').order_by('-date')
    return render(request, 'admin-work.html', {'works': works})


@admin_permission_required('app.manage_work')
def admin_work_create(request):
    form = WorkCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        work = form.save(commit=False)
        work.is_manual = True
        work.created_user = request.user
        work.save()
        form.save_m2m()
        return redirect('admin_work_list')
    return render(request, 'admin-work-create.html', {
        'form': form,
        'title': 'Neuer manueller Dienst',
    })


@admin_permission_required('app.manage_work')
def admin_work_edit(request, work_id):
    work = get_object_or_404(Work, pk=work_id)
    catalogs = Questions_Catalogs.objects.prefetch_related(
        'questions_theory_set'
    ).order_by('level__order', 'order', 'title')
    all_practical = Questions_Practical.objects.select_related('catalog__level').order_by('catalog__level__order', 'pk')
    all_group = Questions_GroupExercise.objects.select_related('level').order_by('level__order', 'number', 'pk')

    all_groups = Group.objects.order_by('name')
    if request.method == 'POST':
        form = WorkForm(request.POST, instance=work)
        if form.is_valid():
            work = form.save()
            work.theory_questions.set(request.POST.getlist('theory_ids'))
            work.practical_exercises.set(request.POST.getlist('practical_ids'))
            work.group_exercises.set(request.POST.getlist('group_ids'))
            group_ids = [int(x) for x in request.POST.getlist('work_group_ids') if x.isdigit()]
            work.groups.set(Group.objects.filter(pk__in=group_ids))
            return redirect('admin_work_list')
    else:
        form = WorkForm(instance=work)

    return render(request, 'admin-work-edit-create.html', {
        'form': form,
        'work': work,
        'catalogs': catalogs,
        'all_practical': all_practical,
        'all_group': all_group,
        'sel_theory_ids': set(work.theory_questions.values_list('pk', flat=True)),
        'sel_practical_ids': set(work.practical_exercises.values_list('pk', flat=True)),
        'sel_group_ids': set(work.group_exercises.values_list('pk', flat=True)),
        'all_groups': all_groups,
        'sel_work_group_ids': set(work.groups.values_list('pk', flat=True)),
    })


@admin_permission_required('app.manage_work')
def admin_work_delete(request, work_id):
    if request.method == 'POST':
        work = get_object_or_404(Work, pk=work_id)
        work.delete()
        messages.success(request, f'Dienst „{work.title}“ gelöscht.')
    return redirect('admin_work_list')


@admin_permission_required('app.sync_divera_work')
def admin_work_sync(request):
    if request.method == 'POST':
        from django.core.management import call_command
        call_command('sync_divera')
    return redirect('admin_work_list')


# ── BENACHRICHTIGUNGEN ────────────────────────────────────────────────────────

@admin_permission_required('app.send_notifications')
def admin_push_message(request):
    form = PushMessageForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        recipients = User.objects.filter(is_active=True)
        if form.cleaned_data['groups']:
            recipients = recipients.filter(groups__in=form.cleaned_data['groups']).distinct()
        _report_push(request, send_push(
            recipients,
            title=form.cleaned_data['title'],
            body=form.cleaned_data['body'],
            url=reverse(form.cleaned_data['target']),
        ))
        return redirect('admin_push_message')

    subscribed = PushSubscription.objects.filter(user__is_active=True)
    return render(request, 'admin-push-message.html', {
        'form': form,
        'push_enabled': push_configured(),
        'subscribed_users': subscribed.values('user').distinct().count(),
        'subscribed_devices': subscribed.count(),
        'own_devices': subscribed.filter(user=request.user).count(),
    })


@admin_permission_required('app.send_notifications')
def admin_push_test(request):
    """Schickt eine Test-Benachrichtigung an alle Geräte des angemeldeten Admins."""
    if request.method == 'POST':
        if not push_configured():
            messages.error(request, 'Push ist auf diesem Server nicht eingerichtet (VAPID-Schlüssel fehlen).')
        elif not PushSubscription.objects.filter(user=request.user).exists():
            messages.warning(request, 'Du hast auf keinem Gerät Push aktiviert. Schalte es zuerst im Profil ein.')
        else:
            sent = send_push([request.user], 'Test-Benachrichtigung',
                             'Push-Benachrichtigungen vom LA-Tool funktionieren.', reverse('admin_push_message'))
            if sent:
                _report_push(request, sent)
            else:
                messages.error(request, 'Test fehlgeschlagen: kein Gerät hat die Benachrichtigung angenommen. Details im Server-Log.')
    return redirect('admin_push_message')


# ── EINSTELLUNGEN ─────────────────────────────────────────────────────────────

@admin_permission_required('app.manage_settings')
def admin_settings(request):
    settings_obj = SiteSettings.get()
    error = None
    if request.method == 'POST':
        raw = request.POST.get('training_pass_threshold', '')
        try:
            val = int(raw)
            if 0 <= val <= 100:
                settings_obj.training_pass_threshold = val
                settings_obj.save()
                return redirect('admin_settings')
            else:
                error = 'Der Wert muss zwischen 0 und 100 liegen.'
        except ValueError:
            error = 'Bitte eine ganze Zahl eingeben.'
    return render(request, 'admin-settings.html', {'settings': settings_obj, 'error': error})


# ── LA-STUFEN ─────────────────────────────────────────────────────────────────

@admin_required
def admin_level_list(request):
    levels = Levels.objects.order_by('order')
    return render(request, 'admin-levels-list.html', {
        'user': request.user,
        'levels': levels,
    })


@admin_permission_required('app.manage_levels')
def admin_level_create(request):
    form = LevelForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('admin_level_list')
    return render(request, 'admin-levels-edit.html', {
        'user': request.user,
        'form': form,
        'title': 'Neue LA-Stufe',
    })


@admin_permission_required('app.manage_levels')
def admin_level_edit(request, level_id):
    level = get_object_or_404(Levels, pk=level_id)
    if request.method == 'POST':
        form = LevelForm(request.POST, request.FILES, instance=level)
        if form.is_valid():
            form.save()
            return redirect('admin_level_list')
    else:
        form = LevelForm(instance=level)
    return render(request, 'admin-levels-edit.html', {
        'user': request.user,
        'form': form,
        'level': level,
        'title': f'Stufe bearbeiten: {level.name}',
    })


@admin_permission_required('app.manage_levels')
def admin_level_delete(request, level_id):
    level = get_object_or_404(Levels, pk=level_id)
    if request.method == 'POST':
        level.delete()
        messages.success(request, f'Stufe „{level.name}“ gelöscht.')
        return redirect('admin_level_list')
    return render(request, 'admin-levels-edit.html', {
        'user': request.user,
        'form': LevelForm(instance=level),
        'level': level,
        'title': f'Stufe löschen: {level.name}',
        'confirm_delete': True,
    })


# ── AUTOMATISCHE GRUPPEN ──────────────────────────────────────────────────────

def _set_group_permissions(group, codenames):
    """App-Rechte der Gruppe auf die gewählten setzen; andere Rechte der Gruppe bleiben unberührt."""
    known = [c for c, _ in APP_PERMISSIONS]
    wanted = set(codenames) & set(known)
    perms = Permission.objects.filter(content_type__app_label='app', codename__in=known)
    group.permissions.remove(*[p for p in perms if p.codename not in wanted])
    group.permissions.add(*[p for p in perms if p.codename in wanted])


def _group_permission_context(group=None):
    selected = set()
    if group is not None:
        selected = set(group.permissions.filter(content_type__app_label='app').values_list('codename', flat=True))
    return {'app_permissions': APP_PERMISSIONS, 'selected_perms': selected}


@admin_permission_required('app.manage_groups')
def admin_autogroup_list(request):
    # Alle Gruppen, auch ohne Regel (z.B. „LA-Tool-Admins“ aus AZURE_GROUP_ADMINS_ID), damit ihre Rechte pflegbar sind
    app_perms = Permission.objects.filter(content_type__app_label='app', codename__in=[c for c, _ in APP_PERMISSIONS])
    groups = (Group.objects.select_related('auto_rule')
              .annotate(member_count=Count('user', distinct=True))
              .prefetch_related(Prefetch('permissions', queryset=app_perms, to_attr='app_perms'))
              .order_by('name'))
    mapped = {name for gid, name in getattr(settings, 'AZURE_GROUPS_MAPPING', {}).items() if gid}
    rows = []
    for group in groups:
        rule = getattr(group, 'auto_rule', None)
        rows.append({'group': group, 'rule': rule, 'mapped': group.name in mapped,
                     'perm_count': len(group.app_perms), 'member_count': group.member_count})
    return render(request, 'admin-autogroups-list.html', {
        'user': request.user,
        'rows': rows,
    })


@admin_permission_required('app.manage_groups')
def admin_autogroup_create(request):
    from .models import AutoGroupRule, DiveraQualification
    from .forms import AutoGroupRuleForm
    all_divera_quals = DiveraQualification.objects.order_by('name')

    if request.method == 'POST':
        form = AutoGroupRuleForm(request.POST)
        if form.is_valid():
            group_name = form.cleaned_data['group_name']
            group, _ = Group.objects.get_or_create(name=group_name)
            try:
                rule = AutoGroupRule.objects.get(group=group)
            except AutoGroupRule.DoesNotExist:
                rule = AutoGroupRule(group=group)
            rule.divera_qual_ids = [int(x) for x in request.POST.getlist('divera_qual_ids') if str(x).isdigit()]
            entra_raw = form.cleaned_data.get('entra_group_ids_text', '')
            rule.entra_group_ids = [ln.strip() for ln in entra_raw.splitlines() if ln.strip()]
            rule.save()
            _set_group_permissions(group, request.POST.getlist('perms'))
            messages.success(request, f'Gruppe „{group.name}“ gespeichert.')
            return redirect('admin_autogroup_list')
    else:
        form = AutoGroupRuleForm()

    return render(request, 'admin-autogroups-edit.html', {
        'user': request.user,
        'form': form,
        'all_divera_quals': all_divera_quals,
        'selected_divera_qual_ids': set(),
        'selected_entra_group_ids': [],
        'title': 'Neue Gruppe',
        **_group_permission_context(),
    })


@admin_permission_required('app.manage_groups')
def admin_autogroup_edit(request, group_id):
    from .models import AutoGroupRule, DiveraQualification
    from .forms import AutoGroupRuleForm
    group = get_object_or_404(Group, pk=group_id)
    rule = AutoGroupRule.objects.filter(group=group).first() or AutoGroupRule(group=group)
    all_divera_quals = DiveraQualification.objects.order_by('name')

    if request.method == 'POST':
        form = AutoGroupRuleForm(request.POST)
        if form.is_valid():
            group_name = form.cleaned_data['group_name']
            if group_name != group.name:
                group.name = group_name
                group.save()
            rule.divera_qual_ids = [int(x) for x in request.POST.getlist('divera_qual_ids') if str(x).isdigit()]
            entra_raw = form.cleaned_data.get('entra_group_ids_text', '')
            rule.entra_group_ids = [ln.strip() for ln in entra_raw.splitlines() if ln.strip()]
            if rule.pk or rule.divera_qual_ids or rule.entra_group_ids:
                rule.save()
            _set_group_permissions(group, request.POST.getlist('perms'))
            messages.success(request, f'Gruppe „{group.name}“ gespeichert.')
            return redirect('admin_autogroup_list')
    else:
        form = AutoGroupRuleForm(initial={
            'group_name': group.name,
            'entra_group_ids_text': '\n'.join(rule.entra_group_ids),
        })

    return render(request, 'admin-autogroups-edit.html', {
        'user': request.user,
        'form': form,
        'rule': rule,
        'group': group,
        'all_divera_quals': all_divera_quals,
        'selected_divera_qual_ids': set(int(x) for x in rule.divera_qual_ids if str(x).isdigit()),
        'selected_entra_group_ids': rule.entra_group_ids,
        'title': f'Gruppe bearbeiten: {group.name}',
        'mapped_entra': group.name in {n for gid, n in getattr(settings, 'AZURE_GROUPS_MAPPING', {}).items() if gid},
        **_group_permission_context(group),
    })


@admin_permission_required('app.manage_groups')
def admin_autogroup_delete(request, group_id):
    group = get_object_or_404(Group, pk=group_id)
    if request.method == 'POST':
        delete_group = request.POST.get('delete_group') == '1'
        try:
            from .models import AutoGroupRule
            AutoGroupRule.objects.filter(group=group).delete()
        except Exception:
            pass
        if delete_group:
            group.delete()
        messages.success(request, f'Regel für „{group.name}“ gelöscht' + (' (Gruppe ebenfalls).' if delete_group else '.'))
        return redirect('admin_autogroup_list')
    return redirect('admin_autogroup_edit', group_id=group_id)

# ── Meldungen zu Fragen ───────────────────────────────────────────────────────

@admin_permission_required('app.manage_theory')
def admin_report_list(request):
    status = request.GET.get('status', 'offen')
    reports = QuestionReport.objects.select_related('question__catalog', 'user', 'resolved_by')
    if status == 'offen':
        reports = reports.filter(resolved_at__isnull=True)
    elif status == 'erledigt':
        reports = reports.filter(resolved_at__isnull=False)
    return render(request, 'admin-reports.html', {
        'reports': reports[:200],
        'status': status,
        'open_count': QuestionReport.objects.filter(resolved_at__isnull=True).count(),
    })


@admin_permission_required('app.manage_theory')
def admin_report_resolve(request, report_id):
    if request.method == 'POST':
        report = get_object_or_404(QuestionReport, pk=report_id)
        if request.POST.get('action') == 'reopen':
            report.resolved_at, report.resolved_by = None, None
        else:
            report.resolved_at, report.resolved_by = timezone.now(), request.user
        report.save(update_fields=['resolved_at', 'resolved_by'])
    return redirect(safe_next_url(request, request.POST.get('next')) or 'admin_report_list')


# ── Lernstand der Jugendlichen ────────────────────────────────────────────────

def _learning_scope(request):
    """Stufe (GET stufe) und ihre Kataloge mit Fragen für die Lernstand-Seiten."""
    levels = list(Levels.objects.filter(is_draft=False).order_by('order'))
    level = next((l for l in levels if l.slug == request.GET.get('stufe')), levels[0] if levels else None)
    catalogs = list(Questions_Catalogs.objects.filter(level=level, is_draft=False).order_by('order', 'title')) if level else []
    ids_by_catalog = learning.catalog_question_ids(catalogs)
    for c in catalogs:
        c.question_ids = ids_by_catalog[c.pk]
    catalogs = [c for c in catalogs if c.question_ids]
    question_ids = [qid for c in catalogs for qid in c.question_ids]
    return levels, level, catalogs, question_ids


def _learner_row(user, attempts, level, catalogs, question_ids):
    history = learning.scores_only(attempts)
    catalog_progress = [learning.summary(c.question_ids, history) for c in catalogs]
    overall = learning.summary(question_ids, history)
    wanted = set(question_ids)
    times = [rows[-1][0] for qid, rows in attempts.items() if qid in wanted]
    return {
        'user': user,
        'catalogs': catalog_progress,
        'progress': overall,
        'readiness': learning.readiness(overall, list(zip(catalogs, catalog_progress)), level.default_exam_pass_pct),
        'last': max(times) if times else None,
        'practiced': overall['counts']['new'] < overall['total'],
        'due': len(learning.due_questions(question_ids, attempts)),
    }


@admin_permission_required('app.view_learning_progress')
def admin_learning(request):
    remember_filters(request, 'admin_learning')
    levels, level, catalogs, question_ids = _learning_scope(request)
    groups = list(Group.objects.order_by('name'))
    group = next((g for g in groups if str(g.pk) == request.GET.get('gruppe')), None)
    show_all = request.GET.get('alle') == '1'

    users = User.objects.filter(is_active=True)
    if group:
        users = users.filter(groups=group)
    users = list(users.order_by('last_name', 'first_name', 'username'))
    attempts = learning.attempts_by_user([u.pk for u in users])
    rows = [_learner_row(u, attempts.get(u.pk, {}), level, catalogs, question_ids) for u in users] if level else []
    hidden = 0
    if not show_all:
        hidden = sum(1 for r in rows if not r['practiced'])
        rows = [r for r in rows if r['practiced']]

    # Schwierigste Fragen der Auswahl: höchste Fehlerquote, nur mit genügend Antworten
    wanted = set(question_ids)
    scores = {}
    for r in rows:
        for qid, tries in attempts.get(r['user'].pk, {}).items():
            if qid in wanted:
                scores.setdefault(qid, []).extend(score for _, score in tries)
    hard = sorted(
        ((1 - sum(s) / len(s), len(s), qid) for qid, s in scores.items() if len(s) >= learning.GLOBAL_MIN_ATTEMPTS),
        reverse=True,
    )[:10]
    q_map = Questions_Theory.objects.select_related('catalog').in_bulk([qid for _, _, qid in hard])
    return render(request, 'admin-learning.html', {
        'levels': levels,
        'level': level,
        'groups': groups,
        'group': group,
        'show_all': show_all,
        'catalogs': catalogs,
        'rows': rows,
        'hidden': hidden,
        'hard_questions': [{'question': q_map[qid], 'error_pct': round(rate * 100), 'answers': n}
                           for rate, n, qid in hard if rate > 0],
    })


@admin_permission_required('app.view_learning_progress')
def admin_learning_user(request, user_id):
    learner = get_object_or_404(User, pk=user_id)
    levels, level, catalogs, question_ids = _learning_scope(request)
    attempts = learning.attempts_by_user([learner.pk]).get(learner.pk, {})
    row = _learner_row(learner, attempts, level, catalogs, question_ids) if level else None
    history = learning.scores_only(attempts)
    weak = [qid for qid in question_ids if history.get(qid) and learning.mastery(history[qid]) < learning.MASTERED]
    weak.sort(key=lambda qid: learning.mastery(history[qid]))
    q_map = Questions_Theory.objects.select_related('catalog').in_bulk(weak[:20])
    assignments = [assignment_status(a, history)
                   for a in _visible_assignments(learner).select_related('level', 'work').prefetch_related('catalogs')]
    return render(request, 'admin-learning-user.html', {
        'learner': learner,
        'levels': levels,
        'level': level,
        'catalogs': list(zip(catalogs, row['catalogs'])) if row else [],
        'row': row,
        'weak_questions': [{'question': q_map[qid], 'mastery': round(learning.mastery(history[qid]) * 100),
                            'tries': len(history[qid])} for qid in weak[:20]],
        'trainings': TrainingResultData.objects.filter(user=learner).order_by('-meta_time')[:10],
        'assignments': assignments,
    })


# ── Lernaufträge ──────────────────────────────────────────────────────────────

def _assignment_progress(assignment, attempts=None, users=None):
    """[(Nutzer, Status)] aller Empfänger eines Lernauftrags, unerfüllte und schwächste zuerst.

    attempts: optional vorab geladene learning.attempts_by_user (für Listen mehrerer Aufträge).
    """
    if users is None:
        users = list(assignment.recipients().order_by('last_name', 'first_name', 'username'))
    if attempts is None:
        attempts = learning.attempts_by_user([u.pk for u in users])
    question_ids = _assignment_question_ids(assignment)  # einmal je Auftrag statt je Person
    result = [(u, assignment_status(assignment, learning.scores_only(attempts.get(u.pk, {})), question_ids=question_ids))
              for u in users]
    return sorted(result, key=lambda pair: (pair[1]['done'], pair[1]['progress']['score']))


@admin_permission_required('app.manage_assignments')
def admin_assignment_list(request):
    assignments = list(LearningAssignment.objects.select_related('level', 'work').prefetch_related('catalogs'))
    today = timezone.localdate()
    recipients = {a.pk: list(a.recipients()) for a in assignments}
    attempts = learning.attempts_by_user({u.pk for users in recipients.values() for u in users})  # einmal für alle
    entries = []
    for a in assignments:
        progress = _assignment_progress(a, attempts, recipients[a.pk])
        entries.append({
            'assignment': a,
            'recipients': len(progress),
            'done': sum(1 for _, s in progress if s['done']),
            'past': a.deadline is not None and a.deadline < today,
        })
    return render(request, 'admin-assignments.html', {
        'current': [e for e in entries if not e['past']],
        'past': [e for e in entries if e['past']],
    })


def _assignment_form_context(form, assignment=None, request=None):
    posted = request is not None and request.method == 'POST'
    return {
        'form': form,
        'assignment': assignment,
        'catalogs': Questions_Catalogs.objects.filter(level__is_draft=False).select_related('level')
                    .order_by('level__order', 'order', 'title'),
        'all_users': User.objects.filter(is_active=True).order_by('last_name', 'first_name'),
        'all_groups': Group.objects.order_by('name'),
        'selected_catalog_ids': _posted_ids(request, 'catalog_ids') if posted else (
            set(assignment.catalogs.values_list('pk', flat=True)) if assignment else set()),
        'selected_user_ids': _posted_ids(request, 'user_ids') if posted else (
            set(assignment.assigned_users.values_list('pk', flat=True)) if assignment else set()),
        'selected_group_ids': _posted_ids(request, 'group_ids') if posted else (
            set(assignment.assigned_groups.values_list('pk', flat=True)) if assignment else set()),
    }


def _save_assignment_relations(request, assignment):
    def ids(name):
        return [int(x) for x in request.POST.getlist(name) if x.isdigit()]
    # Nur Kataloge der gewählten Stufe: nach einem Stufenwechsel bleiben keine fremden hängen
    assignment.catalogs.set(Questions_Catalogs.objects.filter(pk__in=ids('catalog_ids'), level=assignment.level))
    assignment.assigned_users.set(User.objects.filter(pk__in=ids('user_ids')))
    assignment.assigned_groups.set(Group.objects.filter(pk__in=ids('group_ids')))


@admin_permission_required('app.manage_assignments')
def admin_assignment_create(request):
    form = LearningAssignmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        assignment = form.save(commit=False)
        assignment.created_by = request.user
        assignment.save()
        _save_assignment_relations(request, assignment)
        if request.POST.get('notify_push'):
            deadline = assignment.deadline
            _report_push(request, send_push(
                assignment.recipients(),
                title='Neuer Lernauftrag',
                body=f'„{assignment.title}“' + (f' bis {deadline:%d.%m.}' if deadline else ''),
                url=reverse('excercise'),
            ))
        messages.success(request, 'Lernauftrag angelegt.')
        return redirect('admin_assignment_detail', assignment_id=assignment.pk)
    return render(request, 'admin-assignment-edit.html', {**_assignment_form_context(form, request=request), 'title': 'Neuer Lernauftrag'})


@admin_permission_required('app.manage_assignments')
def admin_assignment_edit(request, assignment_id):
    assignment = get_object_or_404(LearningAssignment, pk=assignment_id)
    form = LearningAssignmentForm(request.POST or None, instance=assignment)
    if request.method == 'POST' and form.is_valid():
        form.save()
        _save_assignment_relations(request, assignment)
        messages.success(request, 'Lernauftrag gespeichert.')
        return redirect('admin_assignment_detail', assignment_id=assignment.pk)
    return render(request, 'admin-assignment-edit.html', {
        **_assignment_form_context(form, assignment, request), 'title': 'Lernauftrag bearbeiten'})


@admin_permission_required('app.manage_assignments')
def admin_assignment_detail(request, assignment_id):
    assignment = get_object_or_404(LearningAssignment.objects.select_related('level', 'work'), pk=assignment_id)
    progress = _assignment_progress(assignment)
    return render(request, 'admin-assignment-detail.html', {
        'assignment': assignment,
        'progress': progress,
        'done_count': sum(1 for _, s in progress if s['done']),
        'can_view_details': request.user.has_perm('app.view_learning_progress'),
    })


@admin_permission_required('app.manage_assignments')
def admin_assignment_delete(request, assignment_id):
    assignment = get_object_or_404(LearningAssignment, pk=assignment_id)
    if request.method == 'POST':
        assignment.delete()
        messages.success(request, 'Lernauftrag gelöscht.')
    return redirect('admin_assignment_list')
