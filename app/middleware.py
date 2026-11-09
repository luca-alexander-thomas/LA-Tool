"""Sitzungen: „Angemeldet bleiben“ verlängert sich bei Nutzung."""
import time

# Höchstens einmal täglich verlängern: sonst schriebe jeder Seitenaufruf die Sitzung in die Datenbank
RENEW_AFTER = 24 * 60 * 60


class SlidingSessionMiddleware:
    """Hält dauerhafte Sitzungen (SESSION_COOKIE_AGE) offen, solange die App genutzt wird.

    Sitzungen ohne „Angemeldet bleiben“ (enden beim Schließen des Browsers) bleiben unberührt.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        session = getattr(request, 'session', None)
        if user is not None and user.is_authenticated and session is not None and session.get('remember'):
            now = int(time.time())
            if now - session.get('renewed_at', 0) > RENEW_AFTER:
                session['renewed_at'] = now  # geänderte Sitzung: Django setzt Cookie und Ablauf neu
        return response
