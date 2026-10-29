"""Lernstand im Theorie-Training: aus den gespeicherten Trainingsergebnissen berechnet (keine eigene Tabelle).

Pro Frage zählen die letzten RECENT Versuche (1 = richtig, 0 = falsch, Teilpunkte anteilig):
  - Beherrschung  = Mittelwert dieser Versuche (nie geübt = 0)
  - Lernerfolg    = Mittel der Beherrschung über alle Fragen (in %)

Wiederholung (Lernkartei): Jede richtig beantwortete Frage rückt eine Stufe auf und ist erst nach
INTERVALS[Stufe] Tagen wieder fällig. Wer sie vorher erneut richtig beantwortet, bleibt auf der Stufe.
Eine falsche (oder nur teilweise richtige) Antwort setzt die Frage auf Stufe 0: sofort wieder fällig.
"""
import re
from collections import defaultdict
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from .models import Questions_Theory, TrainingResultData
from .scoring import score_question

RECENT = 3
MASTERED = 0.8       # ab hier „gefestigt“
WEAK = 0.5           # darunter „unsicher“
GLOBAL_MIN_ATTEMPTS = 3
GLOBAL_HARD_RATE = 0.3
GLOBAL_CACHE_KEY = 'learning_global_error_rates'
INTERVALS = (1, 3, 7, 14, 30)   # Tage bis zur nächsten Wiederholung je Stufe der Lernkartei
READY_MARGIN = 20               # „fast bereit“: Lernerfolg höchstens so viele Prozentpunkte unter der Grenze

STATUS_LABELS = {
    'mastered': 'Gefestigt',
    'learning': 'In Arbeit',
    'weak': 'Unsicher',
    'new': 'Noch nicht geübt',
}


def published_theory():
    """Freigegebene Theoriefragen: weder Frage noch Katalog oder Stufe im Entwurf."""
    return Questions_Theory.objects.filter(is_draft=False, catalog__is_draft=False, catalog__level__is_draft=False)


def natural_key(text):
    """Sortierschlüssel, der Zahlen als Zahlen vergleicht: „B1-2“ vor „B1-19“."""
    return [(0, int(part), '') if part.isdigit() else (1, 0, part.lower())
            for part in re.split(r'(\d+)', text or '') if part]


def catalog_question_ids(catalogs):
    """{catalog_id: [freigegebene Fragen-IDs nach Nummer, natürlich sortiert]} für die übergebenen Kataloge."""
    rows = {c.pk: [] for c in catalogs}
    for qid, catalog_id, number in published_theory().filter(catalog__in=catalogs).values_list('pk', 'catalog_id', 'number'):
        rows[catalog_id].append((natural_key(number), qid))
    return {catalog_id: [qid for _, qid in sorted(items)] for catalog_id, items in rows.items()}


def _attempts(results, by_user=False):
    """{question_id: [(Zeitpunkt, Punkte), …] chronologisch} für die gegebenen Trainingsergebnisse.

    by_user=True: {user_id: {question_id: …}} – für Übersichten über viele Nutzer mit einer Abfrage.
    """
    rows = list(results.order_by('meta_time', 'pk').values_list('user_id', 'meta_time', 'questions', 'answers'))
    ids = {qid for _, _, qids, _ in rows for qid in (qids or []) if isinstance(qid, int)}
    questions = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=ids)}
    attempts = defaultdict(lambda: defaultdict(list))
    for user_id, when, qids, answers in rows:
        answers = answers if isinstance(answers, dict) else {}
        for qid in qids or []:
            question = questions.get(qid)
            if question is not None:
                score = score_question(question, answers.get(str(qid), []))
                attempts[user_id if by_user else None][qid].append((when, score))
    if by_user:
        return {user_id: dict(rows) for user_id, rows in attempts.items()}
    return dict(attempts[None])


def attempts_by_user(user_ids):
    return _attempts(TrainingResultData.objects.filter(user_id__in=user_ids), by_user=True)


def scores_only(attempts):
    """{question_id: [Punkte je Versuch]} aus _attempts/user_attempts."""
    return {qid: [score for _, score in rows] for qid, rows in attempts.items()}


def _history(results):
    """{question_id: [Punkte je Versuch, chronologisch]} für die gegebenen Trainingsergebnisse."""
    return scores_only(_attempts(results))


def user_attempts(user):
    if not getattr(user, 'is_authenticated', False):
        return {}
    return _attempts(TrainingResultData.objects.filter(user=user))


def user_history(user):
    return scores_only(user_attempts(user))


def mastery(scores):
    if not scores:
        return 0.0
    recent = scores[-RECENT:]
    return sum(recent) / len(recent)


def status(scores):
    if not scores:
        return 'new'
    value = mastery(scores)
    if value >= MASTERED:
        return 'mastered'
    if value < WEAK:
        return 'weak'
    return 'learning'


def is_hard_for_user(scores):
    """Schon geübt, aber noch nicht gefestigt."""
    return bool(scores) and mastery(scores) < MASTERED


def summary(question_ids, history):
    """Lernerfolg und Statusverteilung für eine Fragenmenge."""
    counts = {key: 0 for key in STATUS_LABELS}
    total_mastery = 0.0
    for qid in question_ids:
        scores = history.get(qid, [])
        counts[status(scores)] += 1
        total_mastery += mastery(scores)
    total = len(question_ids)
    return {
        'total': total,
        'score': round(total_mastery / total * 100) if total else 0,
        'counts': counts,
        'hard': sum(1 for qid in question_ids if is_hard_for_user(history.get(qid, []))),
        'segments': [  # für den gestapelten Balken
            {'key': key, 'label': STATUS_LABELS[key], 'count': counts[key],
             'pct': round(counts[key] / total * 100, 1) if total else 0}
            for key in ('mastered', 'learning', 'weak', 'new')
        ],
    }


def global_error_rates():
    """{question_id: Fehlerquote} über alle Nutzer, nur Fragen mit genügend Versuchen (10 min gecacht)."""
    def compute():
        rates = {}
        for qid, scores in _history(TrainingResultData.objects.all()).items():
            if len(scores) >= GLOBAL_MIN_ATTEMPTS:
                rates[qid] = 1 - sum(scores) / len(scores)
        return rates
    return cache.get_or_set(GLOBAL_CACHE_KEY, compute, 600)


def pick_hard(question_ids, history, count):
    """Schwierige Fragen: zuerst eigene Schwächen (schwächste und zuletzt falsche zuerst),
    dann über alle Nutzer häufig falsch beantwortete, die man selbst noch nicht gefestigt hat."""
    own = [qid for qid in question_ids if is_hard_for_user(history.get(qid, []))]
    own.sort(key=lambda qid: (mastery(history[qid]), history[qid][-1], -len(history[qid])))
    chosen = own[:count]
    if len(chosen) < count:
        rates = global_error_rates()
        taken = set(chosen)
        extra = [qid for qid in question_ids
                 if qid not in taken and rates.get(qid, 0) >= GLOBAL_HARD_RATE
                 and mastery(history.get(qid, [])) < MASTERED]
        extra.sort(key=lambda qid: -rates[qid])
        chosen += extra[:count - len(chosen)]
    return chosen


def pick_new(question_ids, history):
    """Noch nie geübte Fragen."""
    return [qid for qid in question_ids if not history.get(qid)]


# ── Wiederholung (Lernkartei) ─────────────────────────────────────────────────

def schedule(rows):
    """(Stufe, fällig am) einer Frage aus ihren Versuchen [(Zeitpunkt, Punkte)]; nie geübt = (0, None)."""
    box, due = 0, None
    for when, score in rows:
        day = timezone.localdate(when)
        if score < 1:
            box, due = 0, day
        elif due is None or day >= due:
            box = min(box + 1, len(INTERVALS))
            due = day + timedelta(days=INTERVALS[box - 1])
    return box, due


def due_questions(question_ids, attempts, today=None):
    """Fällige Fragen (geübt, Wiederholung heute oder früher), am längsten überfällige zuerst."""
    today = today or timezone.localdate()
    due = []
    for qid in question_ids:
        rows = attempts.get(qid)
        if rows:
            box, day = schedule(rows)
            if day <= today:
                due.append((day, box, qid))
    due.sort(key=lambda item: (item[0], item[1]))
    return [qid for _, _, qid in due]


def due_count_until(question_ids, attempts, until):
    """Anzahl der Fragen, die bis einschließlich `until` fällig werden."""
    return sum(1 for qid in question_ids if attempts.get(qid) and schedule(attempts[qid])[1] <= until)


def pick_today(question_ids, attempts, count, priority_ids=(), today=None):
    """Runde für „Heute lernen“: fällige Wiederholungen, dann neue Fragen (in der übergebenen Reihenfolge,
    also Katalog für Katalog), zuletzt noch nicht gefestigte. Fragen aus priority_ids (Lernauftrag)
    kommen innerhalb jeder Gruppe zuerst. Leer, wenn nichts fällig, nichts neu und alles gefestigt ist."""
    priority = set(priority_ids)

    def first(ids):
        return sorted(ids, key=lambda qid: qid not in priority)  # stabil: Reihenfolge sonst unverändert

    history = scores_only(attempts)
    chosen = (first(due_questions(question_ids, attempts, today)) + first(pick_new(question_ids, history)))[:count]
    if len(chosen) < count:
        taken = set(chosen)
        rest = [qid for qid in question_ids if qid not in taken and history.get(qid) and mastery(history[qid]) < MASTERED]
        rest.sort(key=lambda qid: (mastery(history[qid]), attempts[qid][-1][0]))
        chosen += first(rest)[:count - len(chosen)]
    return chosen


# ── Überblick ─────────────────────────────────────────────────────────────────

READINESS_LABELS = {'green': 'Bereit fürs LA', 'yellow': 'Fast bereit', 'red': 'Noch nicht bereit'}


def readiness(overall, catalog_summaries, pass_pct):
    """Ampel „Bereit fürs LA?“ für eine Stufe; None, wenn es keine Fragen gibt.

    Grün: Lernerfolg ≥ Bestehensgrenze und jeder Katalog mindestens zur Hälfte geübt.
    Gelb: Lernerfolg höchstens READY_MARGIN Prozentpunkte darunter (oder Kataloge fehlen noch).
    catalog_summaries: [(Katalog, summary)]
    """
    if not overall['total']:
        return None
    unpracticed = [c for c, s in catalog_summaries if s['total'] and s['counts']['new'] * 2 > s['total']]
    score = overall['score']
    if score >= pass_pct and not unpracticed:
        state = 'green'
    elif score >= pass_pct - READY_MARGIN:
        state = 'yellow'
    else:
        state = 'red'
    hints = []
    if score < pass_pct:
        hints.append(f'Lernerfolg {score} %, für die Prüfung sind {pass_pct} % nötig.')
    if unpracticed:
        hints.append('Noch kaum geübt: ' + ', '.join(c.short_title or c.title for c in unpracticed) + '.')
    return {'state': state, 'label': READINESS_LABELS[state], 'hints': hints, 'pass_pct': pass_pct}


def progress_timeline(question_ids, attempts, days=60, today=None):
    """[(Tag, Lernerfolg in %)] für jeden Übungstag der letzten `days` Tage und heute.
    Ältere Übungen fließen in den ersten Punkt ein."""
    ids = set(question_ids)
    if not ids:
        return []
    events = sorted((when, qid, score) for qid in ids for when, score in attempts.get(qid, []))
    if not events:
        return []
    today = today or timezone.localdate()
    start = today - timedelta(days=days - 1)
    scores = defaultdict(list)
    total_mastery = 0.0
    points = {}
    for when, qid, score in events:
        before = mastery(scores[qid])
        scores[qid].append(score)
        total_mastery += mastery(scores[qid]) - before
        points[max(timezone.localdate(when), start)] = round(total_mastery / len(ids) * 100)
    points.setdefault(today, round(total_mastery / len(ids) * 100))
    return sorted(points.items())


def practice_streak(days_practiced, today=None):
    """Tage in Folge mit Übung, bis heute (oder bis gestern, solange heute noch nicht geübt wurde)."""
    today = today or timezone.localdate()
    days = set(days_practiced)
    day = today if today in days else today - timedelta(days=1)
    streak = 0
    while day in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


def score_change(user, result, question_ids):
    """(Lernerfolg vor, nach) einem Trainingsergebnis für die Fragenmenge; (None, None) ohne Fragen."""
    if not question_ids:
        return None, None
    upto = TrainingResultData.objects.filter(user=user, meta_time__lte=result.meta_time)
    after = summary(question_ids, _history(upto))['score']
    before = summary(question_ids, _history(upto.exclude(pk=result.pk)))['score']
    return before, after
