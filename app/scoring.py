"""Bewertung einer Theoriefrage – gemeinsam genutzt von Training, Prüfung und Lernstatistik."""


def score_question(q, user_answer):
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
