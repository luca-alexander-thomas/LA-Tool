"""Angaben für Datenschutzerklärung, Nutzungsbedingungen und Impressum.

Alle Werte mit „[BITTE ERGÄNZEN …]“ müssen vor dem Livegang ersetzt werden; die Seiten zeigen bis dahin einen
gelben Hinweis. Die Texte sind Entwürfe und sollten rechtlich geprüft werden (z.B. durch die Datenschutz-
beauftragte Person des THW-Jugend e.V. oder des Ortsverbands).
"""
from django.conf import settings

PLACEHOLDER = '[BITTE ERGÄNZEN'

LEGAL = {
    # Verantwortliche Stelle (Art. 4 Nr. 7 DSGVO)
    'controller_name': 'THW-Jugend Gelsenkirchen',
    'controller_address': 'Adenauerallee 100, 45891 Gelsenkirchen',
    'controller_represented_by': 'Luca-Alexander Thomas',
    'contact_email': 'webmaster@thw-jugend-ge.de',
    # Datenschutzbeauftragte Person (leer lassen, falls keine benannt ist)
    'dpo': 'Luca-Alexander Thomas',
    # Betrieb der Anwendung
    'hoster': 'Netcup GmbH, Hans-Böckler-Allee 7, 30173 Hannover, www.netcup.de Serverstandort: Wien',
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


# Quellcode (AGPL-3.0, Abschnitt 13: Nutzern über das Netz den Quellcode anbieten); Lizenzseite /lizenzen/
SOURCE_URL = 'https://github.com/luca-alexander-thomas/LA-Tool'

# Fremdkomponenten (Name, Version, Lizenz, Link); bei Updates zusammen mit NOTICE.md pflegen
THIRD_PARTY = [
    ('Alpine.js', '3.14.9', 'MIT', 'https://alpinejs.dev'),
    ('PDF.js', '3.11.174', 'Apache-2.0', 'https://mozilla.github.io/pdf.js/'),
    ('Heroicons', '2.2.0', 'MIT', 'https://heroicons.com'),
    ('Tailwind CSS', '4', 'MIT', 'https://tailwindcss.com'),
    ('Django', '6.0.10', 'BSD-3-Clause', 'https://www.djangoproject.com'),
    ('django-tailwind-cli', '4.8.2', 'MIT', 'https://github.com/django-commons/django-tailwind-cli'),
    ('MSAL for Python', '1.39.0', 'MIT', 'https://github.com/AzureAD/microsoft-authentication-library-for-python'),
    ('openpyxl', '3.1.5', 'MIT', 'https://openpyxl.readthedocs.io'),
    ('Pillow', '13.0.0', 'MIT-CMU', 'https://python-pillow.org'),
    ('pywebpush', '2.4.0', 'MPL-2.0', 'https://github.com/web-push-libs/pywebpush'),
    ('cryptography', '50', 'Apache-2.0 oder BSD-3-Clause', 'https://cryptography.io'),
    ('python-dotenv', '1.2.2', 'BSD-3-Clause', 'https://github.com/theskumar/python-dotenv'),
    ('Requests', '2.34.2', 'Apache-2.0', 'https://requests.readthedocs.io'),
    ('WhiteNoise', '6.9.0', 'MIT', 'https://whitenoise.readthedocs.io'),
    ('Gunicorn', '27.0.0', 'MIT', 'https://gunicorn.org'),
    ('mysqlclient', '2.3.1', 'GPL-2.0-or-later', 'https://github.com/PyMySQL/mysqlclient'),
]


def legal_context():
    missing = any(PLACEHOLDER in str(v) for v in LEGAL.values())
    return {
        'legal': LEGAL,
        'legal_incomplete': missing,
        'retention': {key: round(days / 365) if days >= 365 else days for key, days in RETENTION.items()},
        'session_days': settings.SESSION_COOKIE_AGE // 86400,
        'source_url': SOURCE_URL,
        'third_party': THIRD_PARTY,
    }
