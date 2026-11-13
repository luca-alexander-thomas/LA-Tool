from django.http import Http404, JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth, messages
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Q
import json
import logging
import random
import secrets
import time
from datetime import date, timedelta
from django.utils import timezone
from django.urls import reverse
from . import login_function as login_func
from .context_processors import current_la_filter
from . import learning
from .scoring import score_question as _score_question
from django.conf import settings
from la_tool_admin.models import Profile, UserNotification
from la_tool_admin.push import push_configured, safe_internal_url
from .models import (
    Questions_Catalogs, Questions_Theory, TrainingResultData,
    Questions_Practical, Questions_GroupExercise,
    PracticalSelfAssessment, GroupExerciseSelfAssessment,
    Exams, ExamAttempt, ExamResultData, Work, SiteSettings, Levels,
    QuestionBookmark, QuestionReport, LearningAssignment,
)

from .list_filters import remember_filters

logger = logging.getLogger(__name__)


def _user_exam_filter(user):
    """Return a Q filter that matches exams the user can access (direct or via group)."""
    return Q(assigned_users=user) | Q(assigned_groups__in=user.groups.all())


def index(request):
    if not request.user.is_authenticated:
        return render(request, "home.html")

    user = request.user

    # Ohne Divera-Verknüpfung: Wizard nur beim ersten Mal, danach dezente Kachel auf der Startseite
    profile = getattr(user, 'profile', None)
    divera_missing = profile is not None and not profile.divera_ucr
    if divera_missing and not profile.divera_prompt_seen and not request.session.get('first_run_done'):
        type(profile).objects.filter(pk=profile.pk).update(divera_prompt_seen=True)
        return redirect('first_run_wizard')

    training_results = TrainingResultData.objects.filter(
        user=user
    ).order_by('-meta_time')[:5]

    open_exams_count = Exams.objects.filter(
        _user_exam_filter(user), visible=True, archived=False
    ).distinct().count()

    unreleased_results = ExamResultData.objects.filter(
        user=user, state='published'
    ).order_by('-meta_time')[:3]

    next_work = _visible_works(user).filter(date__gte=timezone.now()).order_by('date').first()

    return render(request, "home.html", {
        'user': user,
        'training_results': training_results,
        'open_exams_count': open_exams_count,
        'unreleased_results': unreleased_results,
        'next_work': next_work,
        'divera_missing': divera_missing,
    })


def first_run_wizard(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'skip':
            request.session['first_run_done'] = True
            return redirect('home')

        elif action == 'divera_login':
            username = request.POST.get('divera_username', '').strip()
            password = request.POST.get('divera_password', '').strip()
            if not username or not password:
                return render(request, 'first-run.html', {
                    'user': request.user,
                    'error': 'Bitte Benutzername und Passwort eingeben.',
                    'active_tab': 'login',
                    'divera_username': username,
                })
            result = login_func.link_divera_with_credentials(request.user, username, password)
            if result is True:
                login_func.post_login_setup(request, request.user)
                return redirect('home')
            return render(request, 'first-run.html', {
                'user': request.user,
                'error': result,
                'active_tab': 'login',
                'divera_username': username,
            })

        elif action == 'api_key':
            from la_tool_admin.models import Profile
            api_key = request.POST.get('api_key', '').strip()
            if not api_key:
                return render(request, 'first-run.html', {
                    'user': request.user,
                    'error': 'Bitte einen API-Key eingeben.',
                    'active_tab': 'apikey',
                })
            profile, _ = Profile.objects.get_or_create(user=request.user)
            # Key nur zum Verknüpfen nutzen, nicht speichern
            if login_func.refresh_divera_profile(profile, api_key):
                login_func.post_login_setup(request, request.user)
                return redirect('home')
            return render(request, 'first-run.html', {
                'user': request.user,
                'error': 'API-Key konnte nicht verifiziert werden. Bitte prüfe den Key.',
                'active_tab': 'apikey',
                'api_key_value': api_key,
            })

    return render(request, 'first-run.html', {'user': request.user})


def login(request):
    # Rücksprung nach dem Login (z.B. von einer geschützten Seite)
    next_url = login_func.safe_next_url(request, request.POST.get('next') or request.GET.get('next'))
    if request.user.is_authenticated:
        return redirect(next_url or 'home')
    if request.method == "POST":
        username = request.POST.get("username") or ''
        password = request.POST.get("password")

        if login_func.login_blocked(request, username):
            return render(request, "login.html", {
                "error": 'Zu viele fehlgeschlagene Anmeldeversuche. Bitte warte 15 Minuten.', "next": next_url,
            }, status=429)
        user = login_func.login(username, password, request)
        login_func.record_login_attempt(request, username, success=user is not None)

        # auth_user = auth.authenticate(request, username=username, password=password)
        if user is not None:
            auth.login(request, user)
            login_func.apply_remember(request, request.POST.get('remember') == '1')
            login_func.post_login_setup(request, user)
            return redirect(next_url or 'home')
        else:
            error_message = request.session.pop(
                'login_error', 'Ungültige Anmeldeinformationen')
            return render(request, "login.html", {"error": error_message, "next": next_url})
    return render(request, "login.html", {"next": next_url})


def profile(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    user_profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == 'POST' and request.POST.get('action') == 'learning_reminders':
        user_profile.learning_reminders = request.POST.get('learning_reminders') == '1'
        user_profile.save(update_fields=['learning_reminders'])
        messages.success(request, 'Lern-Erinnerungen ' + ('eingeschaltet.' if user_profile.learning_reminders else 'ausgeschaltet.'))
        return redirect('profile')

    training_results = TrainingResultData.objects.filter(
        user=request.user
    ).order_by('-meta_time')[:10]

    total_sessions = training_results.count()
    scores = [
        (r.meta_reference.get('score', 0), r.meta_reference.get('total', 1))
        for r in training_results
        if r.meta_reference
    ]
    avg_pct = round(
        sum(s / t * 100 for s, t in scores if t > 0) / len(scores)
    ) if scores else None

    return render(request, "profile.html", {
        "user": request.user,
        "training_results": training_results,
        "total_sessions": total_sessions,
        "avg_pct": avg_pct,
        "push_public_key": settings.VAPID_PUBLIC_KEY if push_configured() else '',
        "learning_reminders": user_profile.learning_reminders,
    })


@require_POST
def logout(request):
    auth.logout(request)
    return redirect('home')


def exam_list(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    open_exams = Exams.objects.filter(
        _user_exam_filter(request.user), visible=True, archived=False
    ).distinct().order_by('-pk')

    user_results = {
        r.exam_id: r
        for r in ExamResultData.objects.filter(user=request.user).order_by('meta_time')
        if r.exam_id
    }
    past_results = ExamResultData.objects.filter(
        user=request.user
    ).select_related('exam').order_by('-meta_time')[:10]

    return render(request, 'exams.html', {
        'user': request.user,
        'open_exams': open_exams,
        'user_results': user_results,
        'past_results': past_results,
    })


def exam_start(request, exam_id):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    exam = get_object_or_404(_startable_exams(request.user), pk=exam_id)
    existing = ExamResultData.objects.filter(user=request.user, exam=exam).first()
    running = ExamAttempt.objects.filter(user=request.user, exam=exam).exists()

    if request.method == 'POST' and not existing:
        # Ein laufender Versuch wird fortgesetzt, nie neu gestartet (sonst begänne die Zeit von vorn)
        if not running and not exam.closed:
            try:
                ExamAttempt.objects.create(
                    user=request.user, exam=exam, started_at=timezone.now(),
                    question_ids=list(exam.questions.values_list('pk', flat=True)),
                )
            except IntegrityError:
                pass  # parallel gestartet (Doppelklick, zweites Gerät)
        if running or not exam.closed:
            return redirect('exam_run', exam_id=exam_id)

    question_count = exam.questions.count()
    pass_count = exam.pass_threshold
    pass_pct = round(pass_count / question_count * 100) if question_count else 0
    return render(request, 'exams-exam-start.html', {
        'user': request.user,
        'exam': exam,
        'existing': existing,
        'running': running,
        'question_count': question_count,
        'pass_pct': pass_pct,
        'pass_count': pass_count,
    })


# ── FRAGEN-DURCHGÄNGE (Training und Prüfung) ─────────────────────────────────

def _labeled_choices(q):
    """[(Buchstabe, Text)] aller nicht-leeren Antwortmöglichkeiten; der Buchstabe steht für die Position."""
    return [(chr(ord('a') + i), t) for i, t in enumerate(q.answer_choice or []) if t]


def _selected_texts(q, letters):
    """Antworttexte zu den gewählten Buchstaben (unbekannte Buchstaben werden ignoriert)."""
    choices = q.answer_choice or []
    texts = []
    for letter in letters:
        idx = ord(letter) - ord('a') if isinstance(letter, str) and len(letter) == 1 else -1
        if 0 <= idx < len(choices) and choices[idx]:
            texts.append(choices[idx])
    return texts


def review_rows(question_ids, answers):
    """Je Frage: Antworten, gewählte und richtige Texte, richtig/falsch – für die Ergebnisansichten."""
    q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
    rows = []
    for q_id in question_ids:
        q = q_map.get(q_id)
        if not q:
            continue
        raw = answers.get(str(q_id), '')
        user_letters = raw if isinstance(raw, list) else ([raw] if raw else [])
        user_texts = _selected_texts(q, user_letters)
        correct_texts = q.correct_answers
        rows.append({
            'question': q,
            'labeled_choices': _labeled_choices(q),
            'user_letters': user_letters,
            'user_texts': user_texts,
            'correct_texts': correct_texts,
            'is_correct': set(user_texts) == set(correct_texts),
            'is_multi_answer': q.is_multi_answer,
        })
    return rows


def _question_payload(q):
    """Frage für den Browser – bewusst ohne Lösung."""
    label = ' · '.join(x for x in (q.catalog.short_title if q.catalog else '', q.number or '') if x)
    return {
        'id': q.pk,
        'label': label,
        'question': q.question,
        'help': q.help_reference or '',
        'choices': _labeled_choices(q),
    }


def _answers_from_post(request, questions):
    """Antworten aus dem JSON-Feld 'answers': nur bekannte Fragen und gültige Buchstaben."""
    try:
        raw = json.loads(request.POST.get('answers') or '{}')
    except ValueError:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    answers = {}
    for q in questions:
        given = raw.get(str(q.pk)) or []
        valid = {letter for letter, _ in _labeled_choices(q)}
        answers[str(q.pk)] = sorted({x for x in given if isinstance(x, str) and x in valid}) if isinstance(given, list) else []
    return answers


def _ordered_questions(question_ids):
    q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
    return [q_map[pk] for pk in question_ids if pk in q_map]


# Kulanz für die Abgabe nach Ablauf der Zeit (Netzwerk, langsames Gerät)
EXAM_SUBMIT_GRACE_SEC = 30


def _running_exam(user):
    """Laufender, noch nicht abgelaufener Prüfungsversuch des Nutzers (oder None)."""
    if not user.is_authenticated:
        return None
    for attempt in ExamAttempt.objects.select_related('exam').filter(
            user=user, exam__visible=True, exam__archived=False, exam__closed=False):
        limit = (attempt.exam.time_in_min or 30) * 60 + EXAM_SUBMIT_GRACE_SEC
        if (timezone.now() - attempt.started_at).total_seconds() < limit:
            return attempt
    return None


def _exam_lock(request):
    """Während einer Prüfung keine Lösungen und kein Training: Umleitung zurück zur Prüfung, sonst None."""
    attempt = _running_exam(request.user)
    if attempt is None:
        return None
    messages.warning(request, 'Während deiner Prüfung sind Training und Nachschlagen gesperrt.')
    return redirect('exam_run', exam_id=attempt.exam_id)


def _startable_exams(user):
    """Prüfungen, die der Nutzer starten/fortsetzen darf: zugewiesen, sichtbar, nicht archiviert."""
    return Exams.objects.filter(_user_exam_filter(user), visible=True, archived=False).distinct()


def exam_run(request, exam_id):
    """Ganze Prüfung in einer Seite: Blättern im Browser, Zwischenstand per Autosave, Abgabe auf einmal.

    Die Lösungen bleiben auf dem Server. Nach Ablauf der Zeit (plus Kulanz) zählt nur noch der
    zuletzt automatisch gespeicherte Stand.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    exam = get_object_or_404(_startable_exams(request.user), pk=exam_id)
    is_save = request.method == 'POST' and request.POST.get('action') == 'save'

    attempt = ExamAttempt.objects.filter(user=request.user, exam=exam).first()
    if attempt is None:
        if is_save:
            return JsonResponse({'error': 'Keine laufende Prüfung.'}, status=409)
        if ExamResultData.objects.filter(user=request.user, exam=exam).exists():
            return redirect('exam_result', exam_id=exam_id)  # bereits abgegeben (z.B. auf anderem Gerät)
        return redirect('exam_start', exam_id=exam_id)

    question_ids = attempt.question_ids
    questions = _ordered_questions(question_ids)
    time_limit_sec = (exam.time_in_min or 30) * 60
    elapsed = int((timezone.now() - attempt.started_at).total_seconds())
    # „Gesperrt“ beendet auch laufende Versuche: ab dann zählt nur der letzte Zwischenstand
    in_time = elapsed < time_limit_sec + EXAM_SUBMIT_GRACE_SEC and not exam.closed

    if is_save:
        if not in_time:
            return JsonResponse({'error': 'Die Prüfung wurde gesperrt.' if exam.closed else 'Zeit abgelaufen.'}, status=409)
        attempt.answers = _answers_from_post(request, questions)
        attempt.save(update_fields=['answers'])
        return JsonResponse({'ok': True})

    if request.method == 'POST' or not in_time:
        answers = _answers_from_post(request, questions) if request.method == 'POST' and in_time else attempt.answers
        with transaction.atomic():
            # Wer den Versuch löscht, wertet aus: verhindert doppelte Ergebnisse bei parallelen Abgaben
            deleted, _ = ExamAttempt.objects.filter(pk=attempt.pk).delete()
            if not deleted:
                return redirect('exam_result', exam_id=exam_id)
            _save_exam_result(request.user, exam, question_ids, answers)
        return redirect('exam_result', exam_id=exam_id)

    total = len(question_ids)
    payload = []
    for q in questions:
        data = _question_payload(q)
        data['help'] = ''  # in der Prüfung keine Hinweise
        data['label'] = ''
        payload.append(data)
    return render(request, 'exams-exam.html', {
        'user': request.user,
        'exam': exam,
        'questions': payload,
        'saved_answers': attempt.answers,
        'storage_key': f'exam:{exam_id}:{int(attempt.started_at.timestamp())}',
        'time_remaining_sec': max(0, time_limit_sec - elapsed),
        'pass_count': exam.pass_threshold,
        'pass_pct': round(exam.pass_threshold / total * 100) if total else 0,
        'question_total': total,
    })


def _save_exam_result(user, exam, question_ids, answers):
    q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
    score = 0.0
    for q_id in question_ids:
        q = q_map.get(q_id)
        if q:
            score += _score_question(q, answers.get(str(q_id), ''))
    total = len(question_ids)
    is_passed = score >= exam.pass_threshold if total > 0 else False
    return ExamResultData.objects.create(
        name=exam.name,
        questions=question_ids,
        answers=answers,
        meta_reference={'score': round(score, 2), 'total': total, 'passed': is_passed, 'level': exam.level.slug if exam.level else ''},
        user=user,
        exam=exam,
        state='hidden',
    )


def exam_result(request, exam_id):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    exam = get_object_or_404(Exams, pk=exam_id)
    result = ExamResultData.objects.filter(user=request.user, exam=exam).order_by('-meta_time').first()
    if not result:
        return redirect('exam_list')

    meta = result.meta_reference or {}
    score = meta.get('score', 0)
    total = meta.get('total', 0)
    is_passed = meta.get('passed', False)
    is_released = result.state == 'published'

    questions_data = review_rows(result.questions or [], result.answers or {}) if is_released else []

    # Bestanden: LA-Filter einmalig auf die nächste Stufe – erst nach der Freigabe, sonst verriete der
    # Stufenwechsel das Ergebnis vorab
    advanced = request.session.get('exam_level_advanced', [])
    if is_released and is_passed and exam.level and result.pk not in advanced:
        next_level = exam.level.next_level
        if next_level:
            request.session['la_filter'] = next_level.slug
        request.session['exam_level_advanced'] = (advanced + [result.pk])[-50:]

    pass_count = exam.pass_threshold
    pass_pct = round(pass_count / total * 100) if total else 0
    return render(request, 'exams-exam-summary.html', {
        'user': request.user,
        'exam': exam,
        'result': result,
        'score': score,
        'total': total,
        'is_passed': is_passed,
        'is_released': is_released,
        'questions_data': questions_data,
        'pass_pct': pass_pct,
        'pass_count': pass_count,
    })

def excercise(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    last_trainings = TrainingResultData.objects.filter(
        user=request.user
    ).order_by('-meta_time')[:3]
    sample_theory = _published(Questions_Theory).order_by('?').first()
    sample_practical = _published(Questions_Practical).order_by('?').first()
    sample_group = _published_groups().order_by('?').first()
    overview = _learning_overview(request)

    return render(request, "exercise.html", {
        **_today_plan(overview),
        'last_trainings': last_trainings,
        'theory_progress': overview['progress'],
        'readiness': overview['readiness'],
        'assignments': overview['assignments'],
        'sample_theory': sample_theory,
        'sample_practical': sample_practical,
        'sample_group': sample_group,
    })

def _visible_works(user):
    """Dienste, die der Nutzer sehen darf: keine Entwürfe, nur ohne Gruppe oder für seine Gruppen."""
    return Work.objects.filter(is_draft=False).filter(
        Q(groups__isnull=True) | Q(groups__in=user.groups.all())
    ).distinct()


def work_list(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    works = _visible_works(request.user).order_by('date')

    # Liste: kommende Dienste und vergangene mit Inhalten (Fragen/Übungen), gefiltert nach Jahr
    now = timezone.now()
    list_works = works.filter(
        Q(date__gte=now) | Q(date_end__gte=now)
        | Q(theory_questions__isnull=False)
        | Q(practical_exercises__isnull=False)
        | Q(group_exercises__isnull=False)
    ).distinct()
    current_year = timezone.localtime(now).year
    years = sorted({d.year for d in list_works.dates('date', 'year')} | {current_year}, reverse=True)
    remember_filters(request, 'work')
    year = request.GET.get('jahr', '')
    year = int(year) if year.isdigit() and int(year) in years else current_year
    list_works = list_works.filter(date__year=year)

    # Für den Kalender: Start- und Endtag in lokaler Zeit (Dienste ohne Ende dauern einen Tag)
    calendar_works = []
    for w in works:
        start = timezone.localtime(w.date)
        end = timezone.localtime(w.date_end) if w.date_end else start
        calendar_works.append({
            'title': w.title,
            'url': reverse('work_detail', args=[w.pk]),
            'start': start.strftime('%Y-%m-%d'),
            'end': max(start, end).strftime('%Y-%m-%d'),
            'time': start.strftime('%H:%M'),
        })
    return render(request, 'work.html', {
        'works': list_works,
        'years': years,
        'year': year,
        'calendar_works': calendar_works,
    })


def work_detail(request, work_id):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    work = get_object_or_404(_visible_works(request.user), pk=work_id)
    # Nur freigegebene Aufgaben zeigen (Entwürfe enthielten sonst Lösungen und tote Links)
    return render(request, 'work-detail.html', {
        'work': work,
        'theory_questions': work.theory_questions.filter(pk__in=_published(Questions_Theory)).select_related('catalog'),
        'practical_exercises': work.practical_exercises.filter(pk__in=_published(Questions_Practical)).select_related('catalog'),
        'group_exercises': work.group_exercises.filter(pk__in=_published_groups()),
    })


def work_training_start(request, work_id):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    work = get_object_or_404(_visible_works(request.user), pk=work_id)
    question_ids = list(work.theory_questions.filter(pk__in=_published(Questions_Theory)).values_list('pk', flat=True))
    if not question_ids:
        return redirect('work_detail', work_id=work_id)
    random.shuffle(question_ids)
    _start_training(request, question_ids)
    return redirect('training_run')


# ── THEORIE-TRAINING ─────────────────────────────────────────────────────────

TRAINING_MODES = ('random', 'hard', 'new', 'saved')

def _visible_assignments(user):
    """Lernaufträge des Nutzers: direkt oder über eine Gruppe zugewiesen; ohne Zuweisung gelten sie für alle."""
    if not user.is_authenticated or not user.is_active:
        return LearningAssignment.objects.none()
    return LearningAssignment.objects.filter(level__is_draft=False).filter(
        Q(assigned_users=user) | Q(assigned_groups__in=user.groups.all())
        | Q(assigned_users__isnull=True, assigned_groups__isnull=True)
    ).distinct()


def _assignment_question_ids(assignment):
    """Freigegebene Fragen eines Lernauftrags (gewählte Kataloge, sonst alle der Stufe), Katalog für Katalog."""
    catalogs = list(assignment.catalogs.all()) or list(
        Questions_Catalogs.objects.filter(level=assignment.level, is_draft=False))
    catalogs.sort(key=lambda c: (c.order, c.title, c.pk))
    ids = learning.catalog_question_ids(catalogs)
    return [qid for c in catalogs for qid in ids[c.pk]]


def assignment_status(assignment, history, today=None, question_ids=None):
    """Fortschritt eines Nutzers bei einem Lernauftrag (history: learning.user_history)."""
    today = today or timezone.localdate()
    ids = question_ids if question_ids is not None else _assignment_question_ids(assignment)
    progress = learning.summary(ids, history)
    deadline = assignment.deadline
    return {
        'assignment': assignment,
        'question_ids': ids,
        'progress': progress,
        'done': bool(ids) and progress['score'] >= assignment.target_pct,
        'deadline': deadline,
        'days_left': (deadline - today).days if deadline else None,
    }


def _open_assignments(user, history):
    """Lernaufträge, deren Frist noch nicht vorbei ist (ohne Frist: immer), nächste Frist zuerst."""
    today = timezone.localdate()
    assignments = _visible_assignments(user).select_related('level', 'work').prefetch_related('catalogs')
    open_ = [assignment_status(a, history, today) for a in assignments if a.deadline is None or a.deadline >= today]
    return sorted(open_, key=lambda s: (s['deadline'] is None, s['deadline'] or today))


def _learning_overview(request):
    """Lernstand der aktiven Stufe: Kataloge mit Fortschritt, Ampel, fällige Fragen, offene Lernaufträge.

    Nur Kataloge mit freigegebenen Theoriefragen (reine Praxis-Kataloge erscheinen hier nicht).
    """
    user = request.user
    level = Levels.objects.filter(slug=current_la_filter(request), is_draft=False).first()
    catalogs = list(Questions_Catalogs.objects.filter(
        level=level, is_draft=False).order_by('order', 'title')) if level else []
    ids_by_catalog = learning.catalog_question_ids(catalogs)
    catalogs = [c for c in catalogs if ids_by_catalog[c.pk]]
    question_ids = [qid for c in catalogs for qid in ids_by_catalog[c.pk]]

    tracked = user.is_authenticated
    attempts = learning.user_attempts(user)
    history = learning.scores_only(attempts)
    for c in catalogs:
        c.question_ids = ids_by_catalog[c.pk]
        c.progress = learning.summary(c.question_ids, history)
    progress = learning.summary(question_ids, history)
    return {
        'current_level': level,
        'catalogs': catalogs,
        'question_ids': question_ids,
        'attempts': attempts,
        'history': history,
        'progress': progress,
        'track_progress': tracked,
        'readiness': learning.readiness(progress, [(c, c.progress) for c in catalogs],
                                        level.default_exam_pass_pct) if tracked and level else None,
        'due_count': len(learning.due_questions(question_ids, attempts)) if tracked else 0,
        'assignments': _open_assignments(user, history) if tracked else [],
    }


def _bookmarked_ids(user):
    if not user.is_authenticated:
        return set()
    return set(QuestionBookmark.objects.filter(user=user).values_list('question_id', flat=True))


def training_config(request):
    if (locked := _exam_lock(request)):
        return locked
    overview = _learning_overview(request)
    catalogs = overview['catalogs']
    level = overview['current_level']
    default_count = level.default_training_count if level else 10
    history = overview['history']
    saved_ids = _bookmarked_ids(request.user)
    for c in catalogs:
        c.saved_count = sum(1 for qid in c.question_ids if qid in saved_ids)

    context = {
        **overview,
        'default_count': default_count,
        'mode': 'random',
        'saved_count': len(saved_ids & set(overview['question_ids'])),
    }

    if request.method == 'POST':
        ids_by_catalog = {c.pk: c.question_ids for c in catalogs}
        catalog_ids = {int(x) for x in request.POST.getlist('catalogs') if x.isdigit()} & set(ids_by_catalog)
        count_str = request.POST.get('count', str(default_count))
        count = max(1, min(int(count_str) if count_str.isdigit() else default_count, 100))
        mode = request.POST.get('mode', 'random')
        if mode not in TRAINING_MODES or not request.user.is_authenticated:
            mode = 'random'
        context.update(default_count=count, mode=mode)

        if not catalog_ids:
            return render(request, 'exercise-theorie-training-start.html',
                          {**context, 'error': 'Bitte mindestens einen Katalog auswählen.'})
        # Nur angebotene (freigegebene) Kataloge – keine Entwürfe per manipuliertem POST
        candidates = [qid for cid in catalog_ids for qid in ids_by_catalog[cid]]

        if mode == 'hard':
            question_ids = learning.pick_hard(candidates, history, count)
            empty_error = 'Noch keine schwierigen Fragen: Übe zuerst ein paar Runden – danach erscheinen hier deine Schwachstellen.'
        elif mode == 'new':
            question_ids = learning.pick_new(candidates, history)
            empty_error = 'Du hast in den gewählten Katalogen schon alle Fragen geübt.'
        elif mode == 'saved':
            question_ids = [qid for qid in candidates if qid in saved_ids]
            empty_error = 'In den gewählten Katalogen hast du noch keine Fragen gemerkt. Tippe beim Üben auf das Lesezeichen, um eine Frage zu merken.'
        else:
            question_ids = candidates
            empty_error = 'Keine Fragen in den ausgewählten Katalogen.'
        if not question_ids:
            return render(request, 'exercise-theorie-training-start.html', {**context, 'error': empty_error})

        random.shuffle(question_ids)
        _start_training(request, question_ids[:count])
        return redirect('training_run')

    return render(request, 'exercise-theorie-training-start.html', context)


@require_http_methods(['GET', 'POST'])
def training_today(request):
    """„Heute lernen“: eine Runde ohne Einstellungen (siehe learning.pick_today).

    Optional (nur POST) beschränkt auf einen Katalog („Lesen, dann üben“) oder einen Lernauftrag. Ohne
    Beschränkung gehen Fragen aus offenen Lernaufträgen der Stufe vor. GET ist für App-Verknüpfung und
    den Knopf „Jetzt üben“ in der Erinnerung; es startet nur die Runde in der eigenen Sitzung.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(reverse('training_config'))
    if (locked := _exam_lock(request)):
        return locked
    overview = _learning_overview(request)
    level = overview['current_level']
    count = level.default_training_count if level else 10
    question_ids = overview['question_ids']
    priority = {qid for s in overview['assignments']
                if not s['done'] and level and s['assignment'].level_id == level.pk for qid in s['question_ids']}

    catalog_id = request.POST.get('catalog', '')
    assignment_id = request.POST.get('assignment', '')
    scoped = catalog_id.isdigit() or assignment_id.isdigit()
    if catalog_id.isdigit():
        catalog = next((c for c in overview['catalogs'] if c.pk == int(catalog_id)), None)
        if catalog is None:
            return redirect('theory_lookup')
        question_ids = catalog.question_ids
    elif assignment_id.isdigit():
        assignment = get_object_or_404(_visible_assignments(request.user), pk=assignment_id)
        question_ids = _assignment_question_ids(assignment)
        count = assignment.level.default_training_count

    chosen = learning.pick_today(question_ids, overview['attempts'], count, priority)
    if not chosen and scoped:
        chosen = random.sample(question_ids, min(count, len(question_ids)))  # alles gefestigt: trotzdem üben
    if not chosen:
        messages.success(request, 'Für heute ist alles erledigt: keine Wiederholung fällig und keine neuen Fragen. '
                                  'Du kannst unten trotzdem frei üben.')
        return redirect('training_config')
    _start_training(request, chosen)
    return redirect('training_run')


# So viele Trainings ohne Anmeldung merkt sich die Sitzung, damit nur der Übende seine Auswertung sieht
ANONYMOUS_RESULTS_KEPT = 20


def _remember_anonymous_result(request, result):
    if result.user_id is None:
        kept = [pk for pk in request.session.get('training_anonymous_results', []) if pk != result.pk]
        request.session['training_anonymous_results'] = (kept + [result.pk])[-ANONYMOUS_RESULTS_KEPT:]


def _own_training_result(request, result_id):
    """Training des Nutzers; ohne Anmeldung nur die in dieser Sitzung abgegebenen (sonst 404)."""
    if request.user.is_authenticated:
        return get_object_or_404(TrainingResultData, pk=result_id, user=request.user)
    if result_id not in request.session.get('training_anonymous_results', []):
        raise Http404
    return get_object_or_404(TrainingResultData, pk=result_id, user__isnull=True)


@require_POST
def training_retry(request, result_id):
    """Die nicht (ganz) richtig beantworteten Fragen eines Trainings sofort erneut üben."""
    result = _own_training_result(request, result_id)
    answers = result.answers or {}
    published = set(_published(Questions_Theory).filter(pk__in=result.questions or []).values_list('pk', flat=True))
    wrong = [q.pk for q in _ordered_questions([qid for qid in result.questions or [] if qid in published])
             if _score_question(q, answers.get(str(q.pk), [])) < 1]
    if not wrong:
        return redirect('training_result', result_id=result_id)
    _start_training(request, wrong)
    return redirect('training_run')


def _json_body(request):
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


@require_POST
def question_bookmark(request, q_id):
    """Frage merken ({"saved": true}) oder vergessen ({"saved": false})."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Bitte melde dich an.'}, status=403)
    question = get_object_or_404(_published(Questions_Theory), pk=q_id)
    if _json_body(request).get('saved'):
        QuestionBookmark.objects.get_or_create(user=request.user, question=question)
        return JsonResponse({'saved': True})
    QuestionBookmark.objects.filter(user=request.user, question=question).delete()
    return JsonResponse({'saved': False})


# Schutz vor versehentlichem Massenmelden: so viele unbearbeitete Meldungen darf ein Nutzer haben
MAX_OPEN_REPORTS_PER_USER = 20


@require_POST
def question_report(request, q_id):
    """Fehler in einer Frage melden; erscheint im Admin unter „Meldungen“."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Bitte melde dich an.'}, status=403)
    question = get_object_or_404(_published(Questions_Theory), pk=q_id)
    message = str(_json_body(request).get('message', '')).strip()[:1000]
    if not message:
        return JsonResponse({'error': 'Bitte beschreibe kurz, was nicht stimmt.'}, status=400)
    if QuestionReport.objects.filter(user=request.user, resolved_at__isnull=True).count() >= MAX_OPEN_REPORTS_PER_USER:
        return JsonResponse({'error': 'Du hast schon viele offene Meldungen. Bitte warte, bis sie bearbeitet sind.'}, status=429)
    QuestionReport.objects.create(question=question, user=request.user, message=message)
    return JsonResponse({'ok': True})


def _start_training(request, question_ids):
    request.session['training_question_ids'] = question_ids
    # Neue Kennung je Durchgang: der Browser speichert den Zwischenstand darunter
    request.session['training_run_id'] = secrets.token_hex(8)


# So viele abgegebene Durchgänge merkt sich die Sitzung (gegen doppelte Offline-Abgaben)
FINISHED_RUNS_KEPT = 20


def _remember_finished_run(request, run_id, result):
    if not run_id:
        return
    finished = [pair for pair in request.session.get('training_finished_runs', []) if pair[0] != run_id]
    request.session['training_finished_runs'] = (finished + [[run_id, result.pk]])[-FINISHED_RUNS_KEPT:]


def _late_training_submit(request):
    """Abgabe eines Durchgangs, der offline beendet wurde und erst später gesendet wird.

    Läuft inzwischen ein anderer Durchgang (oder keiner mehr), kommen die Fragen aus dem Formular
    (nur freigegebene, höchstens 100). Ein bereits abgegebener Durchgang wird nicht doppelt gespeichert.
    """
    run_id = request.POST.get('run_id', '')
    for done_id, result_id in request.session.get('training_finished_runs', []):
        if done_id == run_id:
            return redirect('training_result', result_id=result_id) if result_id else redirect('training_config')
    if not request.user.is_authenticated:
        return redirect('training_config')  # ohne Anmeldung keine Offline-Abgabe (Fragen kommen aus dem Formular)
    try:
        posted = json.loads(request.POST.get('question_ids') or '[]')
    except ValueError:
        posted = []
    ids = [qid for qid in posted if isinstance(qid, int)][:100] if isinstance(posted, list) else []
    published = set(_published(Questions_Theory).filter(pk__in=ids).values_list('pk', flat=True))
    questions = _ordered_questions([qid for qid in ids if qid in published])
    if not questions:
        return redirect('training_config')
    result = _save_training_result(request.user, [q.pk for q in questions], _answers_from_post(request, questions))
    _remember_finished_run(request, run_id, result)
    return redirect('training_result', result_id=result.pk)


def training_run(request):
    """Ganzer Durchgang in einer Seite: Blättern läuft im Browser, nur die Abgabe geht an den Server."""
    if request.method == 'POST' and request.POST.get('run_id') and request.POST['run_id'] != request.session.get('training_run_id'):
        return _late_training_submit(request)
    if request.method == 'GET' and (locked := _exam_lock(request)):
        return locked
    question_ids = request.session.get('training_question_ids')
    if not question_ids:
        return redirect('training_config')
    questions = _ordered_questions(question_ids)
    if not questions:
        return redirect('training_config')

    if request.method == 'POST':
        answers = _answers_from_post(request, questions)
        result = _save_training_result(request.user, [q.pk for q in questions], answers)
        _remember_finished_run(request, request.session.get('training_run_id'), result)
        _remember_anonymous_result(request, result)
        for key in ('training_question_ids', 'training_run_id'):
            request.session.pop(key, None)
        return redirect('training_result', result_id=result.pk)

    run_id = request.session.get('training_run_id') or secrets.token_hex(8)
    request.session['training_run_id'] = run_id
    saved_ids = _bookmarked_ids(request.user)
    return render(request, 'exercise-theorie-training.html', {
        'questions': [{**_question_payload(q), 'saved': q.pk in saved_ids} for q in questions],
        'run_id': run_id,
    })


def _save_training_result(user, question_ids, answers):
    if user.is_authenticated:
        from .context_processors import forget_due_count
        forget_due_count(user)
    q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
    score = sum(_score_question(q, answers.get(str(q.pk), [])) for q in q_map.values())
    return TrainingResultData.objects.create(
        name=f'Theorie-Training {date.today().strftime("%d.%m.%Y")}',
        questions=question_ids,
        answers=answers,
        meta_reference={'score': round(score, 2), 'total': len(question_ids)},
        user=user if user.is_authenticated else None,
    )


def training_result(request, result_id):
    """Auswertung eines Trainings; ohne Anmeldung ohne Lernerfolg, Merken und Erinnerungen."""
    result = _own_training_result(request, result_id)
    tracked = request.user.is_authenticated
    question_ids = result.questions or []
    answers = result.answers or {}
    meta = result.meta_reference or {}

    saved_ids = _bookmarked_ids(request.user)
    questions_data = review_rows(question_ids, answers)
    for d in questions_data:
        d['saved'] = d['question'].pk in saved_ids
    wrong = [d for d in questions_data if not d['is_correct']]
    right = [d for d in questions_data if d['is_correct']]

    # Lernerfolg der aktiven Stufe vor und nach diesem Training
    score_before = score_after = None
    if tracked:
        level_ids = list(_published(Questions_Theory).filter(
            catalog__level__slug=current_la_filter(request)).values_list('pk', flat=True))
        score_before, score_after = learning.score_change(request.user, result, level_ids)

    total = meta.get('total', len(questions_data))
    score = meta.get('score', sum(1 for d in questions_data if d['is_correct']))
    pct = round((score / total) * 100) if total > 0 else 0
    slug = request.session.get('la_filter', '')
    level = Levels.objects.filter(slug=slug).first()
    pass_threshold = level.default_training_pass_pct if level else SiteSettings.get().training_pass_threshold

    return render(request, 'exercise-theorie-training-summary.html', {
        'user': request.user,
        'result': result,
        'score': score,
        'total': total,
        'pct': pct,
        'pass_threshold': pass_threshold,
        'questions_data': questions_data,
        'wrong': wrong,
        'right': right,
        'retry_possible': _published(Questions_Theory).filter(pk__in=[d['question'].pk for d in wrong]).exists(),
        'score_before': score_before,
        'score_after': score_after,
        'score_delta': None if score_before is None else score_after - score_before,
        # Nach dem Training Erinnerungen per Push anbieten (app.js pushPrompt, einmal je Gerät)
        'push_public_key': settings.VAPID_PUBLIC_KEY if tracked and push_configured() else '',
    })


def _today_plan(overview):
    """Zahlen für die Karte „Heute lernen“."""
    if not overview['track_progress']:
        return {'today': None}
    level = overview['current_level']
    count = level.default_training_count if level else 10
    due = overview['due_count']
    new = overview['progress']['counts']['new']
    return {'today': {
        'due': due,
        'new': new,
        'count': min(count, due + new) or count,
        'done': not due and not new,
    }}


# ── MEIN LERNSTAND ────────────────────────────────────────────────────────────

def learning_stats(request):
    """Persönliche Statistik: Verlauf, Übungstage in Folge, Kataloge und alle Fragen mit Status."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    overview = _learning_overview(request)
    attempts, history, ids = overview['attempts'], overview['history'], overview['question_ids']
    today = timezone.localdate()
    saved_ids = _bookmarked_ids(request.user)

    q_map = Questions_Theory.objects.select_related('catalog').in_bulk(ids)
    rows = []
    for qid in ids:
        tries = attempts.get(qid, [])
        box, due = learning.schedule(tries)
        status = learning.status(history.get(qid, []))
        rows.append({
            'question': q_map[qid],
            'status': status,
            'status_label': learning.STATUS_LABELS[status],
            'mastery': round(learning.mastery(history.get(qid, [])) * 100),
            'box': box,
            'due': due,
            'is_due': bool(tries) and due <= today,
            'saved': qid in saved_ids,
            'tries': len(tries),
        })

    trainings = TrainingResultData.objects.filter(user=request.user)
    practice_days = {timezone.localdate(t) for t in trainings.values_list('meta_time', flat=True)}
    timeline = learning.progress_timeline(ids, attempts)
    return render(request, 'exercise-theorie-lernstand.html', {
        **overview,
        **_today_plan(overview),
        'rows': rows,
        'saved_count': sum(1 for r in rows if r['saved']),
        'streak': learning.practice_streak(practice_days, today),
        'practice_day_count': len(practice_days),
        'training_count': trainings.count(),
        'answer_count': sum(len(tries) for tries in attempts.values()),
        'due_week': learning.due_count_until(ids, attempts, today + timedelta(days=7)),
        'chart': _timeline_chart(timeline),
        'intervals': learning.INTERVALS,
    })


def _timeline_chart(points, width=600, height=180, pad=28):
    """Koordinaten für das Verlaufsdiagramm (Inline-SVG); None bei weniger als zwei Punkten."""
    if len(points) < 2:
        return None
    first, last = points[0][0], points[-1][0]
    span = max((last - first).days, 1)
    inner_w, inner_h = width - 2 * pad, height - 2 * pad

    def xy(day, value):
        return (round(pad + (day - first).days / span * inner_w, 1), round(pad + (1 - value / 100) * inner_h, 1))

    coords = [xy(day, value) for day, value in points]
    return {
        'width': width,
        'height': height,
        'line': ' '.join(f'{x},{y}' for x, y in coords),
        'area': f'{coords[0][0]},{pad + inner_h} ' + ' '.join(f'{x},{y}' for x, y in coords) + f' {coords[-1][0]},{pad + inner_h}',
        'grid': [{'y': round(pad + (1 - v / 100) * inner_h, 1), 'label': v} for v in (0, 50, 100)],
        'last': {'x': coords[-1][0], 'y': coords[-1][1], 'value': points[-1][1]},
        'start_label': first,
        'end_label': last,
        'points': [{'x': x, 'y': y, 'day': day, 'value': value} for (x, y), (day, value) in zip(coords, points)],
        'left': pad,
        'right': width - pad,
        'bottom': pad + inner_h,
    }


def _published(model):
    """Nur freigegebene Aufgaben: weder die Aufgabe noch Katalog oder Stufe im Entwurf."""
    return model.objects.filter(is_draft=False, catalog__is_draft=False, catalog__level__is_draft=False)


def _published_groups():
    """Freigegebene Gruppenaufgaben (eigenständig, ohne Katalog): Aufgabe und ggf. Stufe nicht im Entwurf."""
    return Questions_GroupExercise.objects.filter(is_draft=False).filter(
        Q(level__isnull=True) | Q(level__is_draft=False))


def _by_catalog(items, catalog_of=lambda item: item.catalog):
    """[(Katalog, [Einträge])] in der Sortierreihenfolge der Kataloge; Einträge behalten ihre Reihenfolge."""
    groups = {}
    for item in items:
        groups.setdefault(catalog_of(item), []).append(item)
    return sorted(groups.items(), key=lambda pair: (pair[0].order, pair[0].title.lower(), pair[0].pk))


# ── THEORIE NACHSCHLAGEN ──────────────────────────────────────────────────────

def theory_lookup(request):
    if (locked := _exam_lock(request)):
        return locked
    """Alle Theoriefragen der aktiven Stufe mit Lösungen zum Nachlesen, gruppiert nach Katalog."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    la = current_la_filter(request)
    questions = list(_published(Questions_Theory).select_related('catalog').filter(catalog__level__slug=la))
    questions.sort(key=lambda q: (learning.natural_key(q.number), q.pk))
    history = learning.user_history(request.user)
    entries = []
    for q in questions:
        correct = set(q.correct_answers)
        status = learning.status(history.get(q.pk, []))
        entries.append({
            'question': q,
            'choices': [(letter, text, text in correct) for letter, text in _labeled_choices(q)],
            'status': status,
            'status_label': learning.STATUS_LABELS[status],
            # Suchtext: Frage, Nummer und Antworten (für die Suche im Browser)
            'search': ' '.join([q.number or '', q.question, *(q.answer_choice or [])]).lower(),
        })
    sections = [{
        'catalog': catalog,
        'items': items,
        'progress': learning.summary([e['question'].pk for e in items], history),
    } for catalog, items in _by_catalog(entries, catalog_of=lambda e: e['question'].catalog)]
    return render(request, 'exercise-theorie-katalog.html', {
        'sections': sections,
        'question_count': len(entries),
        'saved_ids': sorted(_bookmarked_ids(request.user) & {e['question'].pk for e in entries}),
    })


def theory_offline_data(request):
    """Fragen aller freigegebenen Stufen mit Lösungen für das Nachschlagen ohne Netz.

    Bewusst ohne persönliche Daten (kein Lernstand, keine Merkliste): der Service Worker speichert die
    Antwort auf dem Gerät.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Bitte melde dich an.'}, status=403)
    if _running_exam(request.user):
        return JsonResponse({'error': 'Während einer Prüfung nicht verfügbar.'}, status=403)
    questions = list(_published(Questions_Theory).select_related('catalog__level'))
    questions.sort(key=lambda q: (learning.natural_key(q.number), q.pk))
    levels = {}
    for catalog, items in _by_catalog(questions):
        level = catalog.level
        entry = levels.setdefault(level.pk, {'slug': level.slug, 'name': level.name, 'order': level.order, 'catalogs': []})
        entry['catalogs'].append({
            'id': catalog.pk,
            'short_title': catalog.short_title,
            'title': catalog.title,
            'questions': [{
                'number': q.number or '',
                'question': q.question,
                'help': q.help_reference or '',
                'choices': [[letter, text, text in set(q.correct_answers)] for letter, text in _labeled_choices(q)],
            } for q in items],
        })
    response = JsonResponse({
        'generated': timezone.now().isoformat(),
        'levels': sorted(levels.values(), key=lambda l: l['order']),
    }, json_dumps_params={'ensure_ascii': False})
    response['Cache-Control'] = 'private, no-cache'
    return response


def theory_offline_page(request):
    """Hülle für das Nachschlagen ohne Netz (vom Service Worker gecacht, ohne Nutzerdaten)."""
    return render(request, 'pwa/offline-lookup.html')


# ── BENACHRICHTIGUNGEN ────────────────────────────────────────────────────────

def notification_list(request):
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    notifications = list(UserNotification.objects.filter(user=request.user)[:100])
    # Beim Öffnen gelten alle als gelesen; die Liste zeigt trotzdem, was neu war
    UserNotification.objects.filter(user=request.user, read_at__isnull=True).update(read_at=timezone.now())
    return render(request, 'notifications.html', {'notifications': notifications})


def notification_open(request, notification_id):
    """Benachrichtigung als gelesen markieren und ihr Ziel öffnen (Link im Push und in der Liste)."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    notification = get_object_or_404(UserNotification, pk=notification_id, user=request.user)
    if notification.read_at is None:
        notification.read_at = timezone.now()
        notification.save(update_fields=['read_at'])
    return redirect(safe_internal_url(notification.url))


# ── PRAKTISCHE AUFGABEN ───────────────────────────────────────────────────────

def practical_list(request):
    complexity = current_la_filter(request)
    qs = Questions_Practical.objects.select_related('catalog').filter(
        catalog__level__slug=complexity,
        is_draft=False,
        catalog__is_draft=False,
        catalog__level__is_draft=False,
    ).order_by('number', 'pk')

    assessments = {}
    if request.user.is_authenticated:
        for a in PracticalSelfAssessment.objects.filter(user=request.user, question__in=qs):
            assessments[a.question_id] = a.score

    # Nach Katalogen in deren Sortierreihenfolge, innerhalb eines Katalogs nach Nummer
    sections = _by_catalog([(q, assessments.get(q.pk)) for q in qs], catalog_of=lambda pair: pair[0].catalog)

    return render(request, 'exercise-pratical.html', {
        'sections': sections,
        'active_stufe': complexity,
    })


def practical_detail(request, q_id):
    question = get_object_or_404(_published(Questions_Practical), pk=q_id)
    assessment = None
    if request.user.is_authenticated:
        assessment = PracticalSelfAssessment.objects.filter(user=request.user, question=question).first()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('practical_detail', q_id=q_id)
        rating = request.POST.get('rating', '')
        if rating in ('sicher', 'nochmal', 'unsicher'):
            value_map = {'sicher': 100.0, 'nochmal': 50.0, 'unsicher': 0.0}
            new_value = value_map[rating]
            current = assessment.score if assessment and assessment.score is not None else None
            new_score = (current + new_value) / 2 if current is not None else new_value
            PracticalSelfAssessment.objects.update_or_create(
                user=request.user, question=question,
                defaults={'score': new_score},
            )
        return redirect('practical_detail', q_id=q_id)

    return render(request, 'exercise-pratical-detail.html', {
        'question': question,
        'assessment': assessment,
    })


# ── GRUPPENAUFGABEN ───────────────────────────────────────────────────────────

def group_list(request):
    complexity = current_la_filter(request)
    # Aufgaben der gewählten Stufe und Aufgaben für alle Stufen
    qs = _published_groups().select_related('level').filter(
        Q(level__slug=complexity) | Q(level__isnull=True),
    ).order_by('number', 'pk')

    assessments = {}
    if request.user.is_authenticated:
        for a in GroupExerciseSelfAssessment.objects.filter(user=request.user, question__in=qs):
            assessments[a.question_id] = a.score

    questions_with_score = [(q, assessments.get(q.pk)) for q in qs]

    return render(request, 'exercise-groups.html', {
        'questions_with_score': questions_with_score,
        'active_stufe': complexity,
    })


def group_detail(request, q_id):
    question = get_object_or_404(_published_groups().select_related('level'), pk=q_id)
    assessment = None
    if request.user.is_authenticated:
        assessment = GroupExerciseSelfAssessment.objects.filter(user=request.user, question=question).first()

    if request.method == 'POST':
        if not request.user.is_authenticated:
            return redirect('group_detail', q_id=q_id)
        rating = request.POST.get('rating', '')
        if rating in ('sicher', 'nochmal', 'unsicher'):
            value_map = {'sicher': 100.0, 'nochmal': 50.0, 'unsicher': 0.0}
            new_value = value_map[rating]
            current = assessment.score if assessment and assessment.score is not None else None
            new_score = (current + new_value) / 2 if current is not None else new_value
            GroupExerciseSelfAssessment.objects.update_or_create(
                user=request.user, question=question,
                defaults={'score': new_score},
            )
        return redirect('group_detail', q_id=q_id)

    return render(request, 'exercise-groups-detail.html', {
        'question': question,
        'assessment': assessment,
    })


# ── RECHTLICHES UND EIGENE DATEN ──────────────────────────────────────────────

def legal_page(request, template):
    from .legal_info import legal_context
    return render(request, template, legal_context())


def release_notes(request):
    """Neuigkeiten: Version und Notizen des aktuell installierten Releases."""
    from .release import current_release, notes_html
    release = current_release()
    return render(request, 'release-notes.html', {
        'notes': notes_html(release['body']) if release else '',
    })


def robots_txt(request):
    """Geschlossene Anwendung: Suchmaschinen sollen nichts indexieren."""
    from django.http import HttpResponse
    return HttpResponse('User-agent: *\nDisallow: /\n', content_type='text/plain')


def my_data_export(request):
    """Auskunft/Datenübertragbarkeit (Art. 15/20 DSGVO): alle eigenen Daten als JSON-Datei."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    from la_tool_admin.models import PushSubscription
    from .models import (GroupExerciseSelfAssessment, PracticalSelfAssessment, QuestionBookmark, QuestionReport)
    user = request.user
    profile = Profile.objects.filter(user=user).first()
    dt = lambda value: value.isoformat() if value else None  # noqa: E731
    data = {
        'erstellt': timezone.now().isoformat(),
        'konto': {
            'benutzername': user.username, 'vorname': user.first_name, 'nachname': user.last_name,
            'email': user.email, 'registriert': dt(user.date_joined), 'letzte_anmeldung': dt(user.last_login),
            'gruppen': list(user.groups.values_list('name', flat=True)),
        },
        'profil': {
            'anmeldung_ueber': profile.login_source, 'divera_id': profile.divera_ucr,
            'divera_qualifikationen': profile.divera_qualifications, 'divera_gruppen': profile.divera_groups,
            'microsoft_id': profile.entra_oid or None, 'lern_erinnerungen': profile.learning_reminders,
        } if profile else None,
        'trainings': [
            {'zeitpunkt': dt(t.meta_time), 'fragen': t.questions, 'antworten': t.answers, 'ergebnis': t.meta_reference}
            for t in TrainingResultData.objects.filter(user=user).order_by('meta_time')
        ],
        # Punkte nicht freigegebener Prüfungen bleiben bis zur Freigabe verborgen
        'pruefungen': [
            {'pruefung': r.name, 'zeitpunkt': dt(r.meta_time), 'freigegeben': r.state == 'published',
             'antworten': r.answers, 'ergebnis': r.meta_reference if r.state == 'published' else None}
            for r in ExamResultData.objects.filter(user=user).order_by('meta_time')
        ],
        'gemerkte_fragen': list(QuestionBookmark.objects.filter(user=user).values_list('question_id', flat=True)),
        'fehlermeldungen': [
            {'frage': r.question_id, 'text': r.message, 'zeitpunkt': dt(r.created_at)}
            for r in QuestionReport.objects.filter(user=user)
        ],
        'selbsteinschaetzung_praxis': [
            {'aufgabe': a.question_id, 'wert': a.score, 'zeitpunkt': dt(a.updated_at)}
            for a in PracticalSelfAssessment.objects.filter(user=user)
        ],
        'selbsteinschaetzung_gruppe': [
            {'aufgabe': a.question_id, 'wert': a.score, 'zeitpunkt': dt(a.updated_at)}
            for a in GroupExerciseSelfAssessment.objects.filter(user=user)
        ],
        'benachrichtigungen': [
            {'titel': n.title, 'text': n.body, 'zeitpunkt': dt(n.created_at), 'gelesen': dt(n.read_at)}
            for n in UserNotification.objects.filter(user=user)
        ],
        'push_geraete': [
            {'browser': s.user_agent, 'seit': dt(s.created_at)} for s in PushSubscription.objects.filter(user=user)
        ],
    }
    response = JsonResponse(data, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="la-tool-meine-daten-{date.today():%Y-%m-%d}.json"'
    response['Cache-Control'] = 'no-store'
    return response


@require_POST
def my_learning_data_delete(request):
    """Eigene Lerndaten löschen (Trainings, Merkliste, Selbsteinschätzungen, Benachrichtigungen).

    Konto und Prüfungsergebnisse bleiben: Das Konto entsteht bei der nächsten Divera-Anmeldung ohnehin neu,
    Prüfungsergebnisse sind Nachweise – beides löscht auf Antrag ein Admin.
    """
    if not request.user.is_authenticated:
        return redirect_to_login(reverse('profile'))
    if request.POST.get('confirm') != 'LÖSCHEN':
        messages.error(request, 'Bitte zur Bestätigung LÖSCHEN eintippen.')
        return redirect('profile')
    from .models import GroupExerciseSelfAssessment, PracticalSelfAssessment
    user = request.user
    with transaction.atomic():
        for model in (TrainingResultData, QuestionBookmark, PracticalSelfAssessment, GroupExerciseSelfAssessment,
                      UserNotification):
            model.objects.filter(user=user).delete()
    from .context_processors import forget_due_count
    forget_due_count(user)
    messages.success(request, 'Deine Lerndaten wurden gelöscht.')
    return redirect('profile')


# ── BETRIEB ───────────────────────────────────────────────────────────────────

def health(request):
    """Für Monitoring und Proxy: 200, wenn die Datenbank antwortet, sonst 503. Ohne Login, ohne Details."""
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        logger.exception('Health-Check: Datenbank nicht erreichbar')
        return JsonResponse({'status': 'error'}, status=503)
    from .release import current_release
    release = current_release()
    response = JsonResponse({'status': 'ok', 'version': release['tag'] if release else None})
    response['Cache-Control'] = 'no-store'
    return response


# ── LA-FILTER ─────────────────────────────────────────────────────────────────

def set_la_filter(request, level):
    if Levels.objects.filter(slug=level, is_draft=False).exists():
        request.session['la_filter'] = level
    return redirect(login_func.safe_next_url(request, request.META.get('HTTP_REFERER')) or 'home')
