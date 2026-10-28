from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, Http404
from django.contrib import auth
from django.conf import settings
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.db.models import Exists, OuterRef
from app.models import (
    Questions_Catalogs, Questions_Theory, Questions_Practical,
    Questions_GroupExercise, Exams, ExamResultData, Work, SiteSettings, Levels,
)
from app.login_function import post_login_setup
from .forms import CatalogForm, TheoryQuestionForm, PracticalForm, GroupExerciseForm, ExamForm, WorkForm, WorkCreateForm, ImportQuestionForm, LevelForm
from .models import Profile
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
]


def admin_required(view_func):
    """Decorator: Zugriff nur für Nutzer mit der 'access_admin'-Berechtigung (oder Superuser)."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if not request.user.has_perm('app.access_admin'):
            return redirect('home')
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    return wrapper


def send_divera_notification(user_profile, subject, message):
    """Send a Divera private message to a single user via their UCR ID. Returns True on success."""
    import json as _json
    try:
        admin_key = getattr(__import__('la_tool.env', fromlist=['env']), 'DIVERA_ADMIN_USER_API_KEY', '')
        print(f'[Divera] admin_key present: {bool(admin_key)} (len={len(admin_key) if admin_key else 0})')
        if not admin_key:
            print('[Divera] ABORTED: no admin key configured')
            return False

        ucr_id = user_profile.divera_ucr
        print(f'[Divera] ucr_id for user {user_profile.user_id}: {ucr_id!r}')
        if not ucr_id:
            print('[Divera] ABORTED: user has no divera_ucr')
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
        url = f'https://app.divera247.com/api/v2/news?accesskey={admin_key}'
        print(f'[Divera] POST {url}')
        print(f'[Divera] payload: {_json.dumps(payload, ensure_ascii=False)}')
        resp = requests.post(url, json=payload, timeout=10)
        print(f'[Divera] response status: {resp.status_code}')
        print(f'[Divera] response body: {resp.text[:500]}')
        return resp.status_code == 200
    except Exception as e:
        print(f'[Divera] EXCEPTION: {e}')
        return False


@admin_required
def index(request):
    user = request.user
    from django.utils import timezone as tz
    recent_results = ExamResultData.objects.select_related('user', 'exam').order_by('-meta_time')[:5]
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
    })



def sync_user_groups(user, access_token):
    """Synchronisiert Azure AD Gruppenmitgliedschaften zu Django Groups"""
    try:
        # Gruppenmitgliedschaften von Microsoft Graph abrufen
        headers = {'Authorization': f'Bearer {access_token}'}

        # Versuche zuerst mit $filter
        # memberOf abrufen (nur Gruppen, keine rollen)
        graph_url = 'https://graph.microsoft.com/v1.0/me/memberOf'

        graph_response = requests.get(graph_url, headers=headers)

        if graph_response.status_code != 200:
            error_detail = graph_response.json() if graph_response.text else "Keine Details"
            print(
                f"Fehler beim Abrufen der Gruppen: {graph_response.status_code}")
            print(f"Response: {error_detail}")
            return

        groups_data = graph_response.json()
        azure_group_ids = set()
        all_entra_group_ids = []

        # Alle Gruppen die der User in Azure hat - filtere nur Groups (nicht Roles)
        for item in groups_data.get('value', []):
            if '@odata.type' in item and 'microsoft.graph.group' in item['@odata.type']:
                group_id = item.get('id')
                if group_id:
                    all_entra_group_ids.append(group_id)
                    if group_id in getattr(settings, 'AZURE_GROUPS_MAPPING', {}):
                        azure_group_ids.add(group_id)

        # Django Groups via AZURE_GROUPS_MAPPING synchronisieren (legacy)
        django_groups_to_assign = set()

        for azure_group_id in azure_group_ids:
            group_name = settings.AZURE_GROUPS_MAPPING[azure_group_id]
            django_group, created = Group.objects.get_or_create(name=group_name)
            django_groups_to_assign.add(django_group)

        current_groups = user.groups.all()
        mapped_group_names = set(getattr(settings, 'AZURE_GROUPS_MAPPING', {}).values())
        groups_to_remove = current_groups.filter(name__in=mapped_group_names).exclude(
            name__in=[g.name for g in django_groups_to_assign]
        )

        for group in groups_to_remove:
            user.groups.remove(group)

        for group in django_groups_to_assign:
            user.groups.add(group)

        user.save()
        print(f"User {user.username} Gruppen synchronisiert: {[g.name for g in django_groups_to_assign]}")

        # DB-driven auto-group rules
        try:
            from .utils import sync_auto_groups
            sync_auto_groups(user, entra_group_ids=all_entra_group_ids)
        except Exception as e:
            print(f"Fehler beim Sync der Auto-Gruppen: {e}")

    except Exception as e:
        print(f"Fehler beim Synchronisieren der Gruppen: {str(e)}")

# Microsoft OAuth Callbacks


def microsoft_login(request):
    """Initiiert den OAuth Login Flow zu Microsoft Entra ID"""
    if request.user.is_authenticated:
        return redirect('home')

    # MSAL Client erstellen für Authorization URL (ConfidentialClient mit Secret)
    client = msal.ConfidentialClientApplication(
        settings.MICROSOFT_AUTH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_AUTH_TENANT_ID}",
        client_credential=settings.MICROSOFT_AUTH_CLIENT_SECRET,
    )

    # State generieren für CSRF-Protection
    state = str(uuid.uuid4())
    request.session['oauth_state'] = state

    # Authorization URL erstellen
    auth_url = client.get_authorization_request_url(
        scopes=['user.read', 'Directory.Read.All'],
        redirect_uri=settings.MICROSOFT_AUTH_REDIRECT_URI,
        state=state,
    )

    return redirect(auth_url)


def microsoft_callback(request):
    """Verarbeitet den OAuth Callback von Microsoft Entra ID"""
    # State validieren
    stored_state = request.session.get('oauth_state')
    callback_state = request.GET.get('state')

    if not stored_state or stored_state != callback_state:
        return render(request, 'login.html', {'error': 'Sicherheitsfehler: State stimmt nicht überein'})

    # Authorization Code abrufen
    code = request.GET.get('code')
    error = request.GET.get('error')
    error_description = request.GET.get('error_description', '')

    if error:
        return render(request, 'login.html', {
            'error': f'Microsoft Login fehlgeschlagen: {error_description}'
        })

    if not code:
        return render(request, 'login.html', {'error': 'Kein Authorization Code erhalten'})

    try:
        # Token mit Authorization Code austauschen (ConfidentialClient mit Secret)
        client = msal.ConfidentialClientApplication(
            settings.MICROSOFT_AUTH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_AUTH_TENANT_ID}",
            client_credential=settings.MICROSOFT_AUTH_CLIENT_SECRET,
        )

        token_result = client.acquire_token_by_authorization_code(
            code=code,
            scopes=['user.read', 'Directory.Read.All'],
            redirect_uri=settings.MICROSOFT_AUTH_REDIRECT_URI,
        )

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
            headers=headers
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

        # Django User erstellen oder abrufen
        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
            }
        )

        # Profil anlegen/aktualisieren mit login_source
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.login_source = Profile.SOURCE_ENTRA
        profile.save()

        # Gruppenmitgliedschaften synchronisieren
        sync_user_groups(user, access_token)

        # Benutzer einloggen
        auth.login(request, user,
                   backend='django.contrib.auth.backends.ModelBackend')
        post_login_setup(request, user)

        # State aus Session löschen
        if 'oauth_state' in request.session:
            del request.session['oauth_state']

        return redirect('home')

    except Exception as e:
        return render(request, 'login.html', {
            'error': f'Ein Fehler ist aufgetreten: {str(e)}'
        })

# ── NUTZERVERWALTUNG ─────────────────────────────────────────────────────────

@permission_required('app.manage_users', raise_exception=True)
def admin_users(request):
    admin_group = Group.objects.filter(name='LA-Tool-Admins').first()

    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        action = request.POST.get('action')
        target = get_object_or_404(User, pk=user_id)

        if not target.is_superuser and target.pk != request.user.pk:
            if action == 'make_admin':
                group, _ = Group.objects.get_or_create(name='LA-Tool-Admins')
                target.groups.add(group)
                target.is_staff = True
                target.save()
            elif action == 'remove_admin':
                if admin_group:
                    target.groups.remove(admin_group)
                target.is_staff = False
                target.save()
            elif action == 'reset_password' and target.has_usable_password():
                alphabet = string.ascii_letters + string.digits + '!@#$%&*'
                pw = ''.join(secrets.choice(alphabet) for _ in range(12))
                target.set_password(pw)
                target.save()
                request.session['temp_pw_info'] = {
                    'name': target.get_full_name() or target.username,
                    'password': pw,
                }
            elif action == 'delete_user':
                target.delete()
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
                        # Clear Django's per-instance permission cache so the next
                        # request reflects the change immediately
                        for attr in ('_perm_cache', '_user_perm_cache'):
                            if hasattr(target, attr):
                                delattr(target, attr)
                    except Permission.DoesNotExist:
                        pass

        return redirect('admin_users')

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
        ).order_by('last_name', 'first_name').prefetch_related('groups')
    else:
        users = base_qs.order_by('last_name', 'first_name').prefetch_related('groups')

    # Annotate each user: direct permissions and group-inherited ones (for correct button state)
    users_list = list(users)
    for u in users_list:
        u.la_perms_direct = set(
            u.user_permissions.filter(content_type__app_label='app').values_list('codename', flat=True)
        )
        u.la_perms_group = {
            c for c, _ in APP_PERMISSIONS
            if c not in u.la_perms_direct and u.has_perm(f'app.{c}')
        }

    return render(request, 'admin-users.html', {
        'user': request.user,
        'users': users_list,
        'admin_group': admin_group,
        'temp_pw_info': temp_pw_info,
        'app_permissions': APP_PERMISSIONS,
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
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
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
        'group': 'admin_catalog',
        'work': 'admin_work_list',
    }
    ModelClass = model_map.get(model)
    if not ModelClass:
        return redirect('admin_index')
    obj = get_object_or_404(ModelClass, pk=pk)
    obj.is_draft = not obj.is_draft
    obj.save(update_fields=['is_draft'])
    return redirect(redirect_map.get(model, 'admin_index'))


# ── FRAGENKATALOG: KATALOGE ───────────────────────────────────────────────────

@admin_required
def admin_catalog_list(request):
    catalogs = Questions_Catalogs.objects.select_related('level').all().order_by('level__order', 'title')
    counts = {}
    for c in catalogs:
        counts[c.pk] = {
            'theory': Questions_Theory.objects.filter(catalog=c).count(),
            'practical': Questions_Practical.objects.filter(catalog=c).count(),
            'group': Questions_GroupExercise.objects.filter(catalog=c).count(),
        }
    return render(request, 'admin-catalog.html', {
        'user': request.user,
        'catalogs': catalogs,
        'counts': counts,
    })


@permission_required('app.manage_catalogs', raise_exception=True)
def admin_catalog_create(request):
    form = CatalogForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('admin_catalog')
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
    group_qs = Questions_GroupExercise.objects.filter(catalog=catalog).order_by('number', 'pk')
    return render(request, 'admin-catalog-detail.html', {
        'user': request.user,
        'catalog': catalog,
        'form': form,
        'theory_questions': theory_qs,
        'practical_questions': practical_qs,
        'group_questions': group_qs,
        'active_tab': request.GET.get('tab', 'theory'),
    })


@permission_required('app.manage_catalogs', raise_exception=True)
def admin_catalog_update(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        form = CatalogForm(request.POST, request.FILES, instance=catalog)
        if form.is_valid():
            form.save()
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


@permission_required('app.manage_catalogs', raise_exception=True)
def admin_catalog_delete(request, catalog_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    if request.method == 'POST':
        catalog.delete()
        return redirect('admin_catalog')
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── THEORIEFRAGEN ─────────────────────────────────────────────────────────────

@permission_required('app.manage_theory', raise_exception=True)
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
    return render(request, 'admin-question-theory.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'init_choices': ['', '', '', ''],
        'init_correct': [],
        'title': 'Neue Theoriefrage',
    })


@permission_required('app.manage_theory', raise_exception=True)
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


@permission_required('app.manage_theory', raise_exception=True)
def admin_theory_delete(request, catalog_id, q_id):
    question = get_object_or_404(Questions_Theory, pk=q_id, catalog_id=catalog_id)
    if request.method == 'POST':
        question.delete()
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── IMPORT ────────────────────────────────────────────────────────────────────

def _is_truthy(val):
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ('true', '1', 'ja', 'yes', 'x', 'wahr')


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
        wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
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


@permission_required('app.manage_theory', raise_exception=True)
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

            try:
                rows = _parse_import_file(uploaded, uploaded.name)
            except Exception as e:
                form.add_error('file', f'Datei konnte nicht gelesen werden: {e}')
                rows = []

            created = updated = skipped = 0
            errors = []

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


@permission_required('app.manage_theory', raise_exception=True)
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

@permission_required('app.manage_practical', raise_exception=True)
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


@permission_required('app.manage_practical', raise_exception=True)
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


@permission_required('app.manage_practical', raise_exception=True)
def admin_practical_delete(request, catalog_id, q_id):
    question = get_object_or_404(Questions_Practical, pk=q_id, catalog_id=catalog_id)
    if request.method == 'POST':
        question.delete()
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── GRUPPENAUFGABEN ───────────────────────────────────────────────────────────

@permission_required('app.manage_group_exercises', raise_exception=True)
def admin_group_create(request, catalog_id):
    import uuid as _uuid
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
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
                    request.session['pending_file_upload'] = {
                        'model': 'group',
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
        form = GroupExerciseForm()
    return render(request, 'admin-question-group.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'title': 'Neue Gruppenaufgabe',
    })


@permission_required('app.manage_group_exercises', raise_exception=True)
def admin_group_edit(request, catalog_id, q_id):
    catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)
    question = get_object_or_404(Questions_GroupExercise, pk=q_id, catalog=catalog)
    if request.method == 'POST':
        form = GroupExerciseForm(request.POST, request.FILES, instance=question)
        if not request.FILES.get('file'):
            # Exclude file field so save_form_data never re-saves the existing file
            del form.fields['file']
        if form.is_valid():
            form.save()
            return redirect('admin_catalog_detail', catalog_id=catalog_id)
    else:
        form = GroupExerciseForm(instance=question)
    return render(request, 'admin-question-group.html', {
        'user': request.user,
        'form': form,
        'catalog': catalog,
        'question': question,
        'title': 'Gruppenaufgabe bearbeiten',
    })


@permission_required('app.manage_group_exercises', raise_exception=True)
def admin_group_delete(request, catalog_id, q_id):
    question = get_object_or_404(Questions_GroupExercise, pk=q_id, catalog_id=catalog_id)
    if request.method == 'POST':
        question.delete()
    return redirect('admin_catalog_detail', catalog_id=catalog_id)


# ── DATEI-BESTÄTIGUNG BEI DUPLIKATEN ─────────────────────────────────────────

@admin_required
def admin_file_confirm(request):
    import os as _os
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile

    pending = request.session.get('pending_file_upload')
    if not pending:
        return redirect('admin_catalog')

    catalog_id = pending['catalog_id']
    model = pending['model']
    file_perm = 'manage_practical' if model == 'practical' else 'manage_group_exercises'
    if not request.user.has_perm(f'app.{file_perm}'):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    temp_path = pending['temp_path']
    existing_path = pending['existing_path']
    form_data = pending['form_data']

    if request.method == 'POST':
        choice = request.POST.get('choice')
        request.session.pop('pending_file_upload', None)

        catalog = get_object_or_404(Questions_Catalogs, pk=catalog_id)

        if model == 'practical':
            obj = Questions_Practical(catalog=catalog, **form_data)
        else:
            obj = Questions_GroupExercise(catalog=catalog, **form_data)

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
        return redirect('admin_catalog_detail', catalog_id=catalog_id)

    # GET: render confirmation page with previews
    temp_url = default_storage.url(temp_path)
    existing_url = default_storage.url(existing_path)
    filename = _os.path.basename(existing_path)
    back_url = (
        reverse('admin_practical_create', kwargs={'catalog_id': catalog_id})
        if model == 'practical'
        else reverse('admin_group_create', kwargs={'catalog_id': catalog_id})
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

    def _annotate(exams_qs):
        result = []
        for exam in exams_qs:
            results = ExamResultData.objects.filter(exam=exam)
            total_count = results.count()
            passed_count = sum(1 for r in results if (r.meta_reference or {}).get('passed', False))
            result.append({'exam': exam, 'total': total_count, 'passed': passed_count, 'failed': total_count - passed_count})
        return result

    return render(request, 'admin-exams.html', {
        'user': request.user,
        'active_exams': _annotate(active_exams),
        'archived_exams': _annotate(archived_exams),
    })


@permission_required('app.manage_exams', raise_exception=True)
def admin_exam_create(request):
    catalogs = Questions_Catalogs.objects.prefetch_related('questions_theory_set').order_by('level__order', 'title')
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
                    pass
        return redirect('admin_exam_list')

    catalog_data = []
    for c in catalogs:
        qs = Questions_Theory.objects.filter(catalog=c).order_by('number', 'pk')
        catalog_data.append({'catalog': c, 'questions': list(qs)})

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
        'selected_user_ids': set(),
        'selected_group_ids': set(),
        'selected_question_ids': set(),
        'level_defaults_json': json.dumps(level_defaults),
        'title': 'Neue Prüfung',
    })


@permission_required('app.manage_exams', raise_exception=True)
def admin_exam_edit(request, exam_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    catalogs = Questions_Catalogs.objects.order_by('level__order', 'title')
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

    selected_user_ids = set(exam.assigned_users.values_list('pk', flat=True))
    selected_group_ids = set(exam.assigned_groups.values_list('pk', flat=True))
    selected_question_ids = set(exam.questions.values_list('pk', flat=True))

    catalog_data = []
    for c in catalogs:
        qs = Questions_Theory.objects.filter(catalog=c).order_by('number', 'pk')
        catalog_data.append({'catalog': c, 'questions': list(qs)})

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


@permission_required('app.manage_exams', raise_exception=True)
def admin_exam_delete(request, exam_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    if request.method == 'POST':
        exam.delete()
    return redirect('admin_exam_list')


@permission_required('app.manage_exams', raise_exception=True)
def admin_exam_toggle(request, exam_id, field):
    if request.method != 'POST':
        return redirect('admin_exam_list')
    exam = get_object_or_404(Exams, pk=exam_id)
    if field in ('visible', 'closed', 'archived'):
        setattr(exam, field, not getattr(exam, field))
        exam.save()
    return redirect('admin_exam_list')


@permission_required('app.view_exam_results', raise_exception=True)
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


@permission_required('app.view_exam_results', raise_exception=True)
def admin_exam_result_user(request, exam_id, result_id):
    exam = get_object_or_404(Exams, pk=exam_id)
    result = get_object_or_404(ExamResultData, pk=result_id, exam=exam)
    score, total, is_passed = _compute_exam_score(result)

    question_ids = result.questions or []
    answers = result.answers or {}
    q_map = {q.pk: q for q in Questions_Theory.objects.filter(pk__in=question_ids)}
    questions_data = []
    for q_id in question_ids:
        q = q_map.get(q_id)
        if not q:
            continue
        choices = q.answer_choice or []
        while len(choices) < 4:
            choices.append('')
        labeled = [(l, t) for l, t in zip('abcd', choices) if t]
        user_answer = answers.get(str(q_id), '')
        user_letters = user_answer if isinstance(user_answer, list) else ([user_answer] if user_answer else [])
        user_texts = []
        for letter in user_letters:
            if letter in 'abcd':
                idx = 'abcd'.index(letter)
                if idx < len(choices):
                    user_texts.append(choices[idx])
        correct_texts = q.correct_answers
        is_correct = set(user_texts) == set(correct_texts)
        questions_data.append({
            'question': q,
            'labeled_choices': labeled,
            'user_letters': user_letters,
            'user_texts': user_texts,
            'correct_texts': correct_texts,
            'is_correct': is_correct,
        })

    return render(request, 'admin-exam-summary-user.html', {
        'user': request.user,
        'exam': exam,
        'result': result,
        'score': score,
        'total': total,
        'is_passed': is_passed,
        'questions_data': questions_data,
    })


@permission_required('app.release_exam_results', raise_exception=True)
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
    return redirect('admin_exam_result_user', exam_id=exam_id, result_id=result_id)


# ── DIENSTE ───────────────────────────────────────────────────────────────────

@admin_required
def admin_work_list(request):
    works = Work.objects.all().order_by('-date')
    return render(request, 'admin-work.html', {'works': works})


@permission_required('app.manage_work', raise_exception=True)
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


@permission_required('app.manage_work', raise_exception=True)
def admin_work_edit(request, work_id):
    work = get_object_or_404(Work, pk=work_id)
    catalogs = Questions_Catalogs.objects.prefetch_related(
        'questions_theory_set'
    ).order_by('level__order', 'title')
    all_practical = Questions_Practical.objects.select_related('catalog').order_by('catalog__level__order', 'pk')
    all_group = Questions_GroupExercise.objects.select_related('catalog').order_by('catalog__level__order', 'pk')

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


@permission_required('app.manage_work', raise_exception=True)
def admin_work_delete(request, work_id):
    if request.method == 'POST':
        work = get_object_or_404(Work, pk=work_id)
        work.delete()
    return redirect('admin_work_list')


@permission_required('app.sync_divera_work', raise_exception=True)
def admin_work_sync(request):
    if request.method == 'POST':
        from django.core.management import call_command
        call_command('sync_divera')
    return redirect('admin_work_list')


# ── EINSTELLUNGEN ─────────────────────────────────────────────────────────────

@permission_required('app.manage_settings', raise_exception=True)
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


@permission_required('app.manage_levels', raise_exception=True)
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


@permission_required('app.manage_levels', raise_exception=True)
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


@permission_required('app.manage_levels', raise_exception=True)
def admin_level_delete(request, level_id):
    level = get_object_or_404(Levels, pk=level_id)
    if request.method == 'POST':
        level.delete()
        return redirect('admin_level_list')
    return render(request, 'admin-levels-edit.html', {
        'user': request.user,
        'form': LevelForm(instance=level),
        'level': level,
        'title': f'Stufe löschen: {level.name}',
        'confirm_delete': True,
    })


# ── AUTOMATISCHE GRUPPEN ──────────────────────────────────────────────────────

@permission_required('app.manage_groups', raise_exception=True)
def admin_autogroup_list(request):
    from .models import AutoGroupRule
    rules = AutoGroupRule.objects.select_related('group').order_by('group__name')
    return render(request, 'admin-autogroups-list.html', {
        'user': request.user,
        'rules': rules,
    })


@permission_required('app.manage_groups', raise_exception=True)
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
            return redirect('admin_autogroup_list')
    else:
        form = AutoGroupRuleForm()

    return render(request, 'admin-autogroups-edit.html', {
        'user': request.user,
        'form': form,
        'all_divera_quals': all_divera_quals,
        'selected_divera_qual_ids': set(),
        'selected_entra_group_ids': [],
        'title': 'Neue automatische Gruppe',
    })


@permission_required('app.manage_groups', raise_exception=True)
def admin_autogroup_edit(request, group_id):
    from .models import AutoGroupRule, DiveraQualification
    from .forms import AutoGroupRuleForm
    group = get_object_or_404(Group, pk=group_id)
    rule, _ = AutoGroupRule.objects.get_or_create(group=group)
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
            rule.save()
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
    })


@permission_required('app.manage_groups', raise_exception=True)
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
        return redirect('admin_autogroup_list')
    return redirect('admin_autogroup_edit', group_id=group_id)