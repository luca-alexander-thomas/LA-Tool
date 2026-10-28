from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import auth
from django.db.models import Q
import random
import time
from datetime import date
from django.utils import timezone
from . import login_function as login_func
from .models import (
    Questions_Catalogs, Questions_Theory, TrainingResultData,
    Questions_Practical, Questions_GroupExercise,
    PracticalSelfAssessment, GroupExerciseSelfAssessment,
    Exams, ExamResultData, Work, SiteSettings, Levels,
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

    next_work = Work.objects.filter(date__gte=timezone.now()).order_by('date').first()

    return render(request, "home.html", {
        'user': user,
        'training_results': training_results,
        'open_exams_count': open_exams_count,
        'unreleased_results': unreleased_results,
        'next_work': next_work,
    })


def first_run_wizard(request):
    if not request.user.is_authenticated:
        return redirect('login')

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
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = login_func.login(username, password, request)

        # auth_user = auth.authenticate(request, username=username, password=password)
        if user is not None:
            auth.login(request, user)
            login_func.post_login_setup(request, user)
            return redirect('home')
        else:
            error_message = request.session.pop(
                'login_error', 'Ungültige Anmeldeinformationen')
            return render(request, "login.html", {"error": error_message})
    return render(request, "login.html")


def profile(request):
    if not request.user.is_authenticated:
        return redirect('login')

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
    })


def logout(request):
    auth.logout(request)
    return redirect('home')


def exam_list(request):
    if not request.user.is_authenticated:
        return redirect('login')

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
        return redirect('login')

    exam = get_object_or_404(
        Exams.objects.filter(_user_exam_filter(request.user), visible=True).distinct(),
        pk=exam_id,
    )
    existing = ExamResultData.objects.filter(user=request.user, exam=exam).first()

    if request.method == 'POST' and not exam.closed and not existing:
        question_ids = list(exam.questions.values_list('pk', flat=True))
        request.session[f'exam_{exam_id}_question_ids'] = question_ids
        request.session[f'exam_{exam_id}_answers'] = {}
        request.session[f'exam_{exam_id}_current'] = 0
        request.session[f'exam_{exam_id}_started_at'] = int(time.time())
        return redirect('exam_run', exam_id=exam_id)

    question_count = exam.questions.count()
    pass_count = exam.pass_threshold
    pass_pct = round(pass_count / question_count * 100) if question_count else 0
    return render(request, 'exams-exam-start.html', {
        'user': request.user,
        'exam': exam,
        'existing': existing,
        'question_count': question_count,
        'pass_pct': pass_pct,
        'pass_count': pass_count,
    })


def exam_run(request, exam_id):
    if not request.user.is_authenticated:
        return redirect('login')

    exam = get_object_or_404(
        Exams.objects.filter(_user_exam_filter(request.user), visible=True).distinct(),
        pk=exam_id,
    )

    question_ids = request.session.get(f'exam_{exam_id}_question_ids')
    if not question_ids:
        return redirect('exam_start', exam_id=exam_id)

    current = request.session.get(f'exam_{exam_id}_current', 0)
    answers = request.session.get(f'exam_{exam_id}_answers', {})
    total = len(question_ids)
    started_at = request.session.get(f'exam_{exam_id}_started_at', int(time.time()))
    time_limit_sec = (exam.time_in_min or 30) * 60
    elapsed = int(time.time()) - started_at
    time_expired = elapsed >= time_limit_sec

    if request.method == 'POST' or time_expired:
        if not time_expired:
            direction = request.POST.get('direction', 'forward')
            q_id = question_ids[current]
            answers[str(q_id)] = request.POST.getlist('answer')  # empty list = no answer
            request.session[f'exam_{exam_id}_answers'] = answers

            if direction == 'back':
                prev_index = max(0, current - 1)
                request.session[f'exam_{exam_id}_current'] = prev_index
                return redirect('exam_run', exam_id=exam_id)

            next_index = current + 1
            if next_index < total:
                request.session[f'exam_{exam_id}_current'] = next_index
                return redirect('exam_run', exam_id=exam_id)

        result = _save_exam_result(request.user, exam, question_ids, answers)
        # Auto-advance la_filter to next level on pass
        if result and (result.meta_reference or {}).get('passed', False):
            if exam.level:
                next_level = exam.level.next_level
                if next_level:
                    request.session['la_filter'] = next_level.slug
        for key in (f'exam_{exam_id}_question_ids', f'exam_{exam_id}_answers',
                    f'exam_{exam_id}_current', f'exam_{exam_id}_started_at'):
            request.session.pop(key, None)
        return redirect('exam_result', exam_id=exam_id)

    q_id = question_ids[current]
    question = get_object_or_404(Questions_Theory, pk=q_id)
    choices_raw = question.answer_choice or []
    labeled_choices = [(chr(ord('a') + i), t) for i, t in enumerate(choices_raw) if t]
    existing_answers = answers.get(str(q_id), [])
    progress_pct = round((current / total) * 100) if total > 0 else 0
    time_remaining_sec = max(0, time_limit_sec - elapsed)

    pass_count = exam.pass_threshold
    pass_pct = round(pass_count / total * 100) if total else 0
    return render(request, 'exams-exam.html', {
        'user': request.user,
        'exam': exam,
        'question': question,
        'labeled_choices': labeled_choices,
        'existing_answers': existing_answers,
        'question_number': current + 1,
        'question_total': total,
        'progress_pct': progress_pct,
        'started_at': started_at,
        'time_limit_sec': time_limit_sec,
        'time_remaining_sec': time_remaining_sec,
        'pass_pct': pass_pct,
        'pass_count': pass_count,
        'can_go_back': current > 0,
    })


def _score_question(q, user_answer):
    """Returns points for a question (float 0–1)."""
    correct_set = set(q.correct_answers)
    if not correct_set or not q.answer_choice:
        return 0
    choices = q.answer_choice

    # Normalise user answer to list of selected texts
    if isinstance(user_answer, list):
        letters = user_answer
    elif user_answer:
        letters = [user_answer]
    else:
        letters = []

    user_texts = set()
    for letter in letters:
        idx = ord(letter) - ord('a') if letter and len(letter) == 1 else -1
        if 0 <= idx < len(choices) and choices[idx]:
            user_texts.add(choices[idx])

    scoring = q.catalog.multi_answer_scoring if q.catalog else 'all_or_nothing'

    if scoring == 'all_or_nothing':
        return 1 if user_texts == correct_set else 0
    else:  # partial
        correct_selected = len(user_texts & correct_set)
        wrong_selected = len(user_texts - correct_set)
        total_correct = len(correct_set)
        raw = (correct_selected - wrong_selected) / total_correct
        return max(0.0, round(raw, 4))


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
        return redirect('login')

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
        q_map = {q.pk: q for q in Questions_Theory.objects.filter(pk__in=question_ids)}
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
        return redirect('login')

    last_trainings = TrainingResultData.objects.filter(
        user=request.user
    ).order_by('-meta_time')[:3]
    sample_theory = Questions_Theory.objects.order_by('?').first()
    sample_practical = Questions_Practical.objects.order_by('?').first()
    sample_group = Questions_GroupExercise.objects.order_by('?').first()

    return render(request, "exercise.html", {
        'last_trainings': last_trainings,
        'sample_theory': sample_theory,
        'sample_practical': sample_practical,
        'sample_group': sample_group,
    })

def work_list(request):
    if not request.user.is_authenticated:
        return redirect('login')
    from django.db.models import Q as _Q
    qs = Work.objects.filter(is_draft=False)
    if request.user.is_authenticated:
        user_groups = request.user.groups.all()
        qs = qs.filter(_Q(groups__isnull=True) | _Q(groups__in=user_groups)).distinct()
    works = qs.order_by('date')
    return render(request, 'work.html', {'works': works})


def work_detail(request, work_id):
    if not request.user.is_authenticated:
        return redirect('login')
    work = get_object_or_404(Work, pk=work_id)
    return render(request, 'work-detail.html', {'work': work})


def work_training_start(request, work_id):
    if not request.user.is_authenticated:
        return redirect('login')
    work = get_object_or_404(Work, pk=work_id)
    question_ids = list(work.theory_questions.values_list('pk', flat=True))
    if not question_ids:
        return redirect('work_detail', work_id=work_id)
    random.shuffle(question_ids)
    request.session['training_question_ids'] = question_ids
    request.session['training_answers'] = {}
    request.session['training_current'] = 0
    return redirect('training_run')


# ── THEORIE-TRAINING ─────────────────────────────────────────────────────────

def training_config(request):
    la = request.session.get('la_filter', '')
    catalogs = Questions_Catalogs.objects.select_related('level').filter(
        level__slug=la, is_draft=False, level__is_draft=False,
    ).order_by('title')

    current_level = Levels.objects.filter(slug=la).first()
    default_count = current_level.default_training_count if current_level else 10

    if request.method == 'POST':
        catalog_ids = [int(x) for x in request.POST.getlist('catalogs') if x.isdigit()]
        count_str = request.POST.get('count', str(default_count))
        count = int(count_str) if count_str.isdigit() else default_count
        count = max(1, min(count, 100))

        if not catalog_ids:
            return render(request, 'exercise-theorie-training-start.html', {
                'user': request.user,
                'catalogs': catalogs,
                'default_count': count,
                'error': 'Bitte mindestens einen Katalog auswählen.',
            })

        question_ids = list(
            Questions_Theory.objects.filter(
                catalog_id__in=catalog_ids, is_draft=False,
            ).values_list('pk', flat=True)
        )
        if not question_ids:
            return render(request, 'exercise-theorie-training-start.html', {
                'user': request.user,
                'catalogs': catalogs,
                'default_count': count,
                'error': 'Keine Fragen in den ausgewählten Katalogen.',
            })

        random.shuffle(question_ids)
        question_ids = question_ids[:count]

        request.session['training_question_ids'] = question_ids
        request.session['training_answers'] = {}
        request.session['training_current'] = 0

        return redirect('training_run')

    return render(request, 'exercise-theorie-training-start.html', {
        'catalogs': catalogs,
        'default_count': default_count,
    })


def training_run(request):
    question_ids = request.session.get('training_question_ids')
    if not question_ids:
        return redirect('training_config')

    current = request.session.get('training_current', 0)
    answers = request.session.get('training_answers', {})
    total = len(question_ids)

    q_id = question_ids[current]
    question = get_object_or_404(Questions_Theory, pk=q_id)

    if request.method == 'POST':
        direction = request.POST.get('direction', 'forward')
        answers[str(q_id)] = sorted(request.POST.getlist('answer'))  # empty list = no answer
        request.session['training_answers'] = answers

        if direction == 'back':
            prev_index = max(0, current - 1)
            request.session['training_current'] = prev_index
            return redirect('training_run')

        next_index = current + 1
        if next_index >= total:
            result = _save_training_result(request.user, question_ids, answers)
            for key in ('training_question_ids', 'training_answers', 'training_current'):
                request.session.pop(key, None)
            if result and result.pk:
                return redirect('training_result', result_id=result.pk)
            return redirect('training_config')

        request.session['training_current'] = next_index
        return redirect('training_run')

    choices_raw = question.answer_choice or []
    while len(choices_raw) < 4:
        choices_raw.append('')
    labeled_choices = [(l, t) for l, t in zip('abcd', choices_raw) if t]
    existing_answers = answers.get(str(q_id), [])
    progress_pct = round((current / total) * 100) if total > 0 else 0

    return render(request, 'exercise-theorie-training.html', {
        'question': question,
        'labeled_choices': labeled_choices,
        'existing_answers': existing_answers,
        'question_number': current + 1,
        'question_total': total,
        'progress_pct': progress_pct,
        'can_go_back': current > 0,
    })


def _save_training_result(user, question_ids, answers):
    q_map = {q.pk: q for q in Questions_Theory.objects.filter(pk__in=question_ids)}
    score = 0
    for q_id in question_ids:
        q = q_map.get(q_id)
        if not q:
            continue
        choices = q.answer_choice or []
        user_answer = answers.get(str(q_id), '')
        letters = user_answer if isinstance(user_answer, list) else ([user_answer] if user_answer else [])
        selected = set()
        for letter in letters:
            if letter in 'abcd':
                idx = 'abcd'.index(letter)
                if idx < len(choices):
                    selected.add(choices[idx])
        if selected == set(q.correct_answers):
            score += 1
    return TrainingResultData.objects.create(
        name=f'Theorie-Training {date.today().strftime("%d.%m.%Y")}',
        questions=question_ids,
        answers=answers,
        meta_reference={'score': score, 'total': len(question_ids)},
        user=user if user.is_authenticated else None,
    )


def training_result(request, result_id):
    if not request.user.is_authenticated:
        return redirect('login')

    result = get_object_or_404(TrainingResultData, pk=result_id, user=request.user)
    question_ids = result.questions or []
    answers = result.answers or {}
    meta = result.meta_reference or {}

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


# ── PRAKTISCHE AUFGABEN ───────────────────────────────────────────────────────

def practical_list(request):
    complexity = request.session.get('la_filter', '')
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

    questions_with_score = [(q, assessments.get(q.pk)) for q in qs]

    return render(request, 'exercise-pratical.html', {
        'questions_with_score': questions_with_score,
        'active_stufe': complexity,
    })


def practical_detail(request, q_id):
    question = get_object_or_404(Questions_Practical, pk=q_id)
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
    complexity = request.session.get('la_filter', '')
    qs = Questions_GroupExercise.objects.select_related('catalog').filter(
        catalog__level__slug=complexity,
        is_draft=False,
        catalog__is_draft=False,
        catalog__level__is_draft=False,
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
    question = get_object_or_404(Questions_GroupExercise, pk=q_id)
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
    if Levels.objects.filter(slug=level).exists():
        request.session['la_filter'] = level
    referer = request.META.get('HTTP_REFERER', '/')
    return redirect(referer)
