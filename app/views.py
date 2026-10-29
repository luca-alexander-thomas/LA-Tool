from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.contrib.auth.views import redirect_to_login
from django.db import IntegrityError, transaction
from django.db.models import Q
import json
import random
import secrets
import time
from datetime import date
from django.utils import timezone
from django.urls import reverse
from . import login_function as login_func
from .context_processors import current_la_filter
from . import learning
from .scoring import score_question as _score_question
from django.conf import settings
from la_tool_admin.push import push_configured
from .models import (
    Questions_Catalogs, Questions_Theory, TrainingResultData,
    Questions_Practical, Questions_GroupExercise,
    PracticalSelfAssessment, GroupExerciseSelfAssessment,
    Exams, ExamAttempt, ExamResultData, Work, SiteSettings, Levels,
)


def _user_exam_filter(user):
    """Return a Q filter that matches exams the user can access (direct or via group)."""
    return Q(assigned_users=user) | Q(assigned_groups__in=user.groups.all())


def index(request):
    if not request.user.is_authenticated:
        return render(request, "home.html")

    user = request.user

    # First-Run-Wizard: once per session for users without Divera link
    try:
        has_divera = bool(user.profile.divera_api_key)
    except Exception:
        has_divera = True
    if not has_divera and not request.session.get('first_run_done'):
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
            profile.divera_api_key = api_key
            profile.save(update_fields=['divera_api_key'])
            ok = login_func.refresh_divera_profile(profile)
            if ok:
                login_func.post_login_setup(request, request.user)
                return redirect('home')
            profile.divera_api_key = ''
            profile.save(update_fields=['divera_api_key'])
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
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = login_func.login(username, password, request)

        # auth_user = auth.authenticate(request, username=username, password=password)
        if user is not None:
            auth.login(request, user)
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
    in_time = elapsed < time_limit_sec + EXAM_SUBMIT_GRACE_SEC

    if is_save:
        if not in_time:
            return JsonResponse({'error': 'Zeit abgelaufen.'}, status=409)
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
            result = _save_exam_result(request.user, exam, question_ids, answers)
        # Bei Bestehen den LA-Filter auf die nächste Stufe setzen
        if (result.meta_reference or {}).get('passed', False) and exam.level:
            next_level = exam.level.next_level
            if next_level:
                request.session['la_filter'] = next_level.slug
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

    question_ids = result.questions or []
    answers = result.answers or {}
    questions_data = []
    if is_released:
        q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
        for q_id in question_ids:
            q = q_map.get(q_id)
            if not q:
                continue
            choices = q.answer_choice or []
            labeled = [(chr(ord('a') + i), t) for i, t in enumerate(choices) if t]

            raw_answer = answers.get(str(q_id), '')
            user_letters = raw_answer if isinstance(raw_answer, list) else ([raw_answer] if raw_answer else [])
            user_texts = []
            for letter in user_letters:
                idx = ord(letter) - ord('a') if letter and len(letter) == 1 else -1
                if 0 <= idx < len(choices) and choices[idx]:
                    user_texts.append(choices[idx])

            correct_set = set(q.correct_answers)
            is_correct = set(user_texts) == correct_set

            questions_data.append({
                'question': q,
                'labeled_choices': labeled,
                'user_letters': user_letters,
                'user_texts': user_texts,
                'correct_texts': list(correct_set),
                'is_correct': is_correct,
                'is_multi_answer': q.is_multi_answer,
            })

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
    level_question_ids = list(_published(Questions_Theory).filter(
        catalog__level__slug=current_la_filter(request)).values_list('pk', flat=True))
    theory_progress = learning.summary(level_question_ids, learning.user_history(request.user))

    return render(request, "exercise.html", {
        'last_trainings': last_trainings,
        'theory_progress': theory_progress,
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

TRAINING_MODES = ('random', 'hard', 'new')


def training_config(request):
    la = current_la_filter(request)
    catalogs = list(Questions_Catalogs.objects.select_related('level').filter(
        level__slug=la, is_draft=False, level__is_draft=False,
    ).order_by('order', 'title'))

    current_level = Levels.objects.filter(slug=la).first()
    default_count = current_level.default_training_count if current_level else 10

    # Lernstand: Fragen je Katalog und bisherige Versuche des Nutzers
    ids_by_catalog = {c.pk: [] for c in catalogs}
    for qid, catalog_id in _published(Questions_Theory).filter(
            catalog__in=catalogs).values_list('pk', 'catalog_id'):
        ids_by_catalog[catalog_id].append(qid)
    history = learning.user_history(request.user)
    for c in catalogs:
        c.progress = learning.summary(ids_by_catalog[c.pk], history)
    overall = learning.summary([qid for ids in ids_by_catalog.values() for qid in ids], history)

    context = {
        'catalogs': catalogs,
        'default_count': default_count,
        'progress': overall,
        'mode': 'random',
        'track_progress': request.user.is_authenticated,
    }

    if request.method == 'POST':
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
        else:
            question_ids = candidates
            empty_error = 'Keine Fragen in den ausgewählten Katalogen.'
        if not question_ids:
            return render(request, 'exercise-theorie-training-start.html', {**context, 'error': empty_error})

        random.shuffle(question_ids)
        _start_training(request, question_ids[:count])
        return redirect('training_run')

    return render(request, 'exercise-theorie-training-start.html', context)


def _start_training(request, question_ids):
    request.session['training_question_ids'] = question_ids
    # Neue Kennung je Durchgang: der Browser speichert den Zwischenstand darunter
    request.session['training_run_id'] = secrets.token_hex(8)


def training_run(request):
    """Ganzer Durchgang in einer Seite: Blättern läuft im Browser, nur die Abgabe geht an den Server."""
    question_ids = request.session.get('training_question_ids')
    if not question_ids:
        return redirect('training_config')
    questions = _ordered_questions(question_ids)
    if not questions:
        return redirect('training_config')

    if request.method == 'POST':
        answers = _answers_from_post(request, questions)
        result = _save_training_result(request.user, [q.pk for q in questions], answers)
        for key in ('training_question_ids', 'training_run_id'):
            request.session.pop(key, None)
        if result.user_id:
            return redirect('training_result', result_id=result.pk)
        return redirect('training_config')

    run_id = request.session.get('training_run_id') or secrets.token_hex(8)
    request.session['training_run_id'] = run_id
    return render(request, 'exercise-theorie-training.html', {
        'questions': [_question_payload(q) for q in questions],
        'run_id': run_id,
    })


def _save_training_result(user, question_ids, answers):
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
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    result = get_object_or_404(TrainingResultData, pk=result_id, user=request.user)
    question_ids = result.questions or []
    answers = result.answers or {}
    meta = result.meta_reference or {}

    q_map = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=question_ids)}
    questions_data = []
    for q_id in question_ids:
        q = q_map.get(q_id)
        if not q:
            continue
        user_answer = answers.get(str(q_id), '')
        user_letters = user_answer if isinstance(user_answer, list) else ([user_answer] if user_answer else [])
        user_texts = _selected_texts(q, user_letters)
        correct_texts = q.correct_answers

        questions_data.append({
            'question': q,
            'labeled_choices': _labeled_choices(q),
            'user_letters': user_letters,
            'user_texts': user_texts,
            'correct_texts': correct_texts,
            'is_correct': set(user_texts) == set(correct_texts),
            'is_multi_answer': q.is_multi_answer,
        })

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
    })


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
    """Alle Theoriefragen der aktiven Stufe mit Lösungen zum Nachlesen, gruppiert nach Katalog."""
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    la = current_la_filter(request)
    questions = _published(Questions_Theory).select_related('catalog').filter(
        catalog__level__slug=la,
    ).order_by('number', 'pk')
    entries = []
    for q in questions:
        correct = set(q.correct_answers)
        entries.append({
            'question': q,
            'choices': [(letter, text, text in correct) for letter, text in _labeled_choices(q)],
            # Suchtext: Frage, Nummer und Antworten (für die Suche im Browser)
            'search': ' '.join([q.number or '', q.question, *(q.answer_choice or [])]).lower(),
        })
    sections = _by_catalog(entries, catalog_of=lambda e: e['question'].catalog)
    return render(request, 'exercise-theorie-katalog.html', {
        'sections': [(catalog, items, ' '.join(e['search'] for e in items)) for catalog, items in sections],
        'question_count': len(entries),
    })


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


# ── LA-FILTER ─────────────────────────────────────────────────────────────────

def set_la_filter(request, level):
    if Levels.objects.filter(slug=level, is_draft=False).exists():
        request.session['la_filter'] = level
    return redirect(login_func.safe_next_url(request, request.META.get('HTTP_REFERER')) or 'home')
