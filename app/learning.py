"""Lernstand im Theorie-Training: aus den gespeicherten Trainingsergebnissen berechnet (keine eigene Tabelle).

Pro Frage zählen die letzten RECENT Versuche (1 = richtig, 0 = falsch, Teilpunkte anteilig):
  - Beherrschung  = Mittelwert dieser Versuche (nie geübt = 0)
  - Lernerfolg    = Mittel der Beherrschung über alle Fragen (in %)
"""
from collections import defaultdict

from django.core.cache import cache

from .models import Questions_Theory, TrainingResultData
from .scoring import score_question

RECENT = 3
MASTERED = 0.8       # ab hier „gefestigt“
WEAK = 0.5           # darunter „unsicher“
GLOBAL_MIN_ATTEMPTS = 3
GLOBAL_HARD_RATE = 0.3
GLOBAL_CACHE_KEY = 'learning_global_error_rates'

STATUS_LABELS = {
    'mastered': 'Gefestigt',
    'learning': 'In Arbeit',
    'weak': 'Unsicher',
    'new': 'Noch nicht geübt',
}


def _history(results):
    """{question_id: [Punkte je Versuch, chronologisch]} für die gegebenen Trainingsergebnisse."""
    rows = list(results.order_by('meta_time', 'pk').values_list('questions', 'answers'))
    ids = {qid for qids, _ in rows for qid in (qids or []) if isinstance(qid, int)}
    questions = {q.pk: q for q in Questions_Theory.objects.select_related('catalog').filter(pk__in=ids)}
    history = defaultdict(list)
    for qids, answers in rows:
        answers = answers if isinstance(answers, dict) else {}
        for qid in qids or []:
            question = questions.get(qid)
            if question is not None:
                history[qid].append(score_question(question, answers.get(str(qid), [])))
    return dict(history)


def user_history(user):
    if not getattr(user, 'is_authenticated', False):
        return {}
    return _history(TrainingResultData.objects.filter(user=user))


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
