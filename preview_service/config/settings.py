"""
Preview Microservice — minimal Django settings.

This service has no database, no auth, no sessions.
It is a stateless HTTP worker that scrapes metadata from URLs.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv('SECRET_KEY', 'preview-service-dev-key-not-for-production')
DEBUG = os.getenv('DEBUG', 'True') == 'True'
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = [
    'django.contrib.contenttypes',
    'django.contrib.auth',
    'preview',
]

MIDDLEWARE = [
    'django.middleware.common.CommonMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# No DB needed — stateless service
DATABASES = {}

USE_TZ = True
TIME_ZONE = 'UTC'

# Request timeouts (seconds)
SCRAPER_TIMEOUT = int(os.getenv('SCRAPER_TIMEOUT', '10'))
SCRAPER_MAX_CONTENT_LENGTH = int(os.getenv('SCRAPER_MAX_CONTENT_LENGTH', str(1024 * 1024)))  # 1MB

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(levelname)s %(asctime)s %(name)s %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
