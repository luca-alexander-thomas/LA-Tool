import os
from pathlib import Path
from dotenv import load_dotenv

# .env liegt im la_tool/-Verzeichnis (neben manage.py)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

# Sicher voreingestellt: ohne DEBUG in der .env läuft der Produktionsmodus
DEBUG = os.getenv('DEBUG', 'False').strip().lower() in ('1', 'true', 'yes', 'on')

SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured('SECRET_KEY fehlt in der .env (siehe .env.example).')
    SECRET_KEY = 'nur-fuer-die-lokale-entwicklung'

HOSTNAME = os.getenv('HOSTNAME', 'localhost')

DATABASE = {
    'Type': os.getenv('DATABASE_TYPE', 'sqlite3'),
    'sqlite3': {
        'FILENAME': os.getenv('DB_SQLITE_FILE', 'db.sqlite3'),
    },
    'mysql': {
        'HOST': os.getenv('DB_MYSQL_HOST', 'localhost'),
        'PORT': int(os.getenv('DB_MYSQL_PORT', '3306')),
        'USER': os.getenv('DB_MYSQL_USER', ''),
        'PASSWORD': os.getenv('DB_MYSQL_PASSWORD', ''),
        'DATABASE': os.getenv('DB_MYSQL_NAME', ''),
    },
}

AZURE_CLIENT_ID = os.getenv('AZURE_CLIENT_ID', '')
AZURE_CLIENT_SECRET = os.getenv('AZURE_CLIENT_SECRET', '')
AZURE_TENANT_ID = os.getenv('AZURE_TENANT_ID', '')
AZURE_REDIRECT_URI = os.getenv('AZURE_REDIRECT_URI', 'http://localhost:8000/microsoft-callback/')

AZURE_GROUPS_MAPPING = {
    os.getenv('AZURE_GROUP_ADMINS_ID', ''): 'LA-Tool-Admins',
    os.getenv('AZURE_GROUP_USERS_ID', ''): 'LA-Tool-Benutzer',
}

DIVERA_ADMIN_USER_API_KEY = os.getenv('DIVERA_ADMIN_USER_API_KEY', '')
DIVERA_Site_ID = os.getenv('DIVERA_SITE_ID', '20369')
DIVERA_EVENTS_GROUP = os.getenv('DIVERA_EVENTS_GROUP', 'Jugendliche')

# Web Push (PWA-Benachrichtigungen). Schlüssel erzeugen: python manage.py generate_vapid_keys
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_SUBJECT = os.getenv('VAPID_SUBJECT', '')
