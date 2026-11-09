"""Angaben für Datenschutzerklärung, Nutzungsbedingungen und Impressum.

Alle Werte mit „[BITTE ERGÄNZEN …]“ müssen vor dem Livegang ersetzt werden; die Seiten zeigen bis dahin einen
gelben Hinweis. Die Texte sind Entwürfe und sollten rechtlich geprüft werden (z.B. durch die Datenschutz-
beauftragte Person des THW-Jugend e.V. oder des Ortsverbands).
"""
from django.conf import settings

PLACEHOLDER = '[BITTE ERGÄNZEN'

LEGAL = {
    # Verantwortliche Stelle (Art. 4 Nr. 7 DSGVO)
    'controller_name': '[BITTE ERGÄNZEN: z.B. THW-Jugend Gelsenkirchen im THW-Jugend e.V.]',
    'controller_address': '[BITTE ERGÄNZEN: Straße Nr., PLZ Ort]',
    'controller_represented_by': '[BITTE ERGÄNZEN: vertretungsberechtigte Person, z.B. Jugendbeauftragte*r]',
    'contact_email': '[BITTE ERGÄNZEN: Kontakt-E-Mail]',
    # Datenschutzbeauftragte Person (leer lassen, falls keine benannt ist)
    'dpo': '[BITTE ERGÄNZEN: Name und Kontakt der/des Datenschutzbeauftragten oder leer lassen]',
    # Betrieb der Anwendung
    'hoster': '[BITTE ERGÄNZEN: Hoster/Rechenzentrum und Standort, z.B. „eigener Server bei …, Deutschland“]',
    'operator_note': 'Die Anwendung wird ehrenamtlich von Luca-Alexander Thomas für die THW-Jugend Gelsenkirchen betrieben.',
    # Zuständige Aufsichtsbehörde (Sitz der verantwortlichen Stelle in NRW)
    'authority': 'Landesbeauftragte für Datenschutz und Informationsfreiheit Nordrhein-Westfalen (LDI NRW), '
                 'Kavalleriestraße 2–4, 40213 Düsseldorf, www.ldi.nrw.de',
    'last_updated': '09.11.2026',
}

# Aufbewahrungsfristen (siehe Befehl cleanup_data); hier für die Datenschutzerklärung
RETENTION = {
    'training_days': 2 * 365,
    'exam_days': 3 * 365,
    'left_account_days': 365,
    'notification_days': 90,
    'resolved_report_days': 365,
}


def legal_context():
    missing = any(PLACEHOLDER in str(v) for v in LEGAL.values())
    return {
        'legal': LEGAL,
        'legal_incomplete': missing,
        'retention': {key: round(days / 365) if days >= 365 else days for key, days in RETENTION.items()},
        'session_days': settings.SESSION_COOKIE_AGE // 86400,
    }
