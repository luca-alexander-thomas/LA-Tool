import os
from pathlib import Path
from dotenv import load_dotenv

# .env liegt im la_tool/-Verzeichnis (neben manage.py)
load_dotenv(Path(__file__).resolve().parent.parent / '.env')

SECRET_KEY = os.getenv('SECRET_KEY', 'CHANGE-ME-IN-PRODUCTION')

DEBUG = os.getenv('DEBUG', 'True') == 'True'

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
