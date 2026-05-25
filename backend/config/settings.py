"""
Django settings — Module 8: Advanced Optimization & Production Readiness.
"""

from datetime import timedelta
from pathlib import Path
from celery.schedules import crontab
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third-party
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    # Local
    'core',
    'shortener',
    'api',
]

MIDDLEWARE = [
    'config.middleware.SecurityHeadersMiddleware',
    'config.middleware.ProfilingMiddleware',          # request timing
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# --------------------------------------------------------------------------
# Databases
# --------------------------------------------------------------------------

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

_db_url = config('DATABASE_URL', default='')
if _db_url:
    from urllib.parse import urlparse as _p
    _u = _p(_db_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _u.path[1:], 'USER': _u.username, 'PASSWORD': _u.password,
        'HOST': _u.hostname, 'PORT': _u.port,
    }

_replica_url = config('ANALYTICS_REPLICA_URL', default='')
if _replica_url:
    from urllib.parse import urlparse as _p
    _r = _p(_replica_url)
    DATABASES['analytics_replica'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _r.path[1:], 'USER': _r.username, 'PASSWORD': _r.password,
        'HOST': _r.hostname, 'PORT': _r.port,
        'TEST': {'MIRROR': 'default'},
    }
else:
    DATABASES['analytics_replica'] = DATABASES['default'].copy()
    DATABASES['analytics_replica']['TEST'] = {'MIRROR': 'default'}

DATABASE_ROUTERS = ['config.routers.AnalyticsReplicaRouter']

# --------------------------------------------------------------------------
# Redis URL (shared by cache + Celery broker)
# --------------------------------------------------------------------------

REDIS_URL = config('REDIS_URL', default='redis://localhost:6379/0')

# --------------------------------------------------------------------------
# Caching — Redis with LocMemCache fallback for dev
# --------------------------------------------------------------------------

if not config('REDIS_URL', default=''):
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'urlshortener-dev',
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': REDIS_URL,
            'KEY_PREFIX': 'urlshortener',
            'TIMEOUT': 60 * 15,
        }
    }

# --------------------------------------------------------------------------
# Celery — Async task queue
# --------------------------------------------------------------------------

CELERY_BROKER_URL = config('CELERY_BROKER_URL', default=REDIS_URL)
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default=REDIS_URL)
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60        # hard limit: 30 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60   # soft limit: 25 minutes

# --------------------------------------------------------------------------
# Celery Beat — Periodic task schedule
# --------------------------------------------------------------------------

CELERY_BEAT_SCHEDULE = {
    'clean-expired-urls-nightly': {
        'task': 'shortener.tasks.clean_expired_urls_task',
        'schedule': crontab(hour=0, minute=0),   # midnight UTC
        'options': {'expires': 3600},
    },
    'warm-popular-url-cache': {
        'task': 'shortener.tasks.warm_popular_url_cache_task',
        'schedule': crontab(minute=0, hour='*/6'),  # every 6 hours
        'options': {'expires': 3600},
    },
}

# --------------------------------------------------------------------------
# Authentication & Password Hashing
# --------------------------------------------------------------------------

AUTH_USER_MODEL = 'core.User'

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
     'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_BLACKLIST_ENABLED': True,
}

# --------------------------------------------------------------------------
# Django REST Framework
# --------------------------------------------------------------------------

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'login': '5/minute',
    },
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
    'EXCEPTION_HANDLER': 'api.exceptions.custom_exception_handler',
}

# --------------------------------------------------------------------------
# API Documentation
# --------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    'TITLE': 'URL Shortener API',
    'DESCRIPTION': 'Enterprise-Grade URL Shortener — Module 8: Async, Caching & Monitoring.',
    'VERSION': '3.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# --------------------------------------------------------------------------
# Structured JSON Logging
# --------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'json': {
            '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
            'format': '%(levelname)s %(asctime)s %(name)s %(module)s %(message)s',
        },
        'verbose': {
            'format': '[%(asctime)s] %(levelname)s [%(name)s:%(lineno)s] %(message)s',
            'datefmt': '%d/%b/%Y %H:%M:%S',
        },
    },
    'handlers': {
        'console_json': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'json',
        },
    },
    'loggers': {
        # Capture all 500-level errors from Django's request cycle
        'django': {
            'handlers': ['console_json'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['console_json'],
            'level': 'ERROR',       # logs every 500 in JSON
            'propagate': False,
        },
        'django.security': {
            'handlers': ['console_json'],
            'level': 'WARNING',     # logs all security warnings (CSRF, SuspiciousOp)
            'propagate': False,
        },
        # Application loggers
        'api': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
        'shortener': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
        'core': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
        'config': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
        # Celery task logging
        'celery': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
        'celery.task': {'handlers': ['console_json'], 'level': 'INFO', 'propagate': False},
    },
}

# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'   # needed for: python manage.py collectstatic
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --------------------------------------------------------------------------
# Preview Microservice — Service Discovery
# --------------------------------------------------------------------------
# In Docker Compose, services discover each other by container name.
# Override PREVIEW_SERVICE_URL in .env for different environments.
# --------------------------------------------------------------------------

PREVIEW_SERVICE_URL = config('PREVIEW_SERVICE_URL', default='http://preview_service:8001')
PREVIEW_SERVICE_TIMEOUT = int(config('PREVIEW_SERVICE_TIMEOUT', default='10'))

# --------------------------------------------------------------------------
# CORS — Frontend Integration (React/Next.js)
# --------------------------------------------------------------------------
# Allow the frontend origin to call the API.
# In production, replace '*' with your actual frontend domain.
# --------------------------------------------------------------------------

INSTALLED_APPS += ['corsheaders']  # requires: pip install django-cors-headers
MIDDLEWARE.insert(1, 'corsheaders.middleware.CorsMiddleware')

CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
).split(',')

CORS_ALLOW_METHODS = ['DELETE', 'GET', 'OPTIONS', 'PATCH', 'POST', 'PUT']
CORS_ALLOW_HEADERS = [
    'accept', 'accept-encoding', 'authorization',
    'content-type', 'origin', 'user-agent', 'x-request-id',
]
CORS_ALLOW_CREDENTIALS = True
