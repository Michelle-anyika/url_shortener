"""
Django settings for config project — Module 7: Authentication & Authorization.
"""

from datetime import timedelta
from pathlib import Path
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Security
# --------------------------------------------------------------------------

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*').split(',')

# Extra security flags (effective in production with DEBUG=False)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG   # HTTPS-only in production
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
    'rest_framework_simplejwt.token_blacklist',  # enables token logout
    'drf_spectacular',
    # Local
    'core',
    'shortener',
    'api',
]

MIDDLEWARE = [
    'config.middleware.SecurityHeadersMiddleware',   # security headers first
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
    from urllib.parse import urlparse as _urlparse
    _u = _urlparse(_db_url)
    DATABASES['default'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _u.path[1:],
        'USER': _u.username,
        'PASSWORD': _u.password,
        'HOST': _u.hostname,
        'PORT': _u.port,
    }

_replica_url = config('ANALYTICS_REPLICA_URL', default='')
if _replica_url:
    from urllib.parse import urlparse as _urlparse
    _r = _urlparse(_replica_url)
    DATABASES['analytics_replica'] = {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': _r.path[1:],
        'USER': _r.username,
        'PASSWORD': _r.password,
        'HOST': _r.hostname,
        'PORT': _r.port,
        'TEST': {'MIRROR': 'default'},
    }
else:
    DATABASES['analytics_replica'] = DATABASES['default'].copy()
    DATABASES['analytics_replica']['TEST'] = {'MIRROR': 'default'}

DATABASE_ROUTERS = ['config.routers.AnalyticsReplicaRouter']


# --------------------------------------------------------------------------
# Caching
# --------------------------------------------------------------------------

_redis_url = config('REDIS_URL', default='')
if _redis_url:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
            'LOCATION': _redis_url,
            'KEY_PREFIX': 'urlshortener',
            'TIMEOUT': 60 * 15,
        }
    }
else:
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'urlshortener-dev',
        }
    }


# --------------------------------------------------------------------------
# Authentication & Password Hashing
# --------------------------------------------------------------------------

AUTH_USER_MODEL = 'core.User'

# Django uses PBKDF2 by default. Argon2 is stronger — install argon2-cffi.
# Falls back to PBKDF2 if argon2-cffi is not installed.
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
# JWT Configuration (djangorestframework-simplejwt)
# --------------------------------------------------------------------------

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=60),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,   # old refresh tokens are blacklisted on rotation
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

    # JWT is the default authentication method
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),

    # Throttling — protect against brute force and abuse
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
        'rest_framework.throttling.ScopedRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day',
        'login': '5/minute',   # brute-force protection on the login endpoint
    },

    # Return 403 for unauthenticated requests (not 401) unless overridden
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ],
}


# --------------------------------------------------------------------------
# API Documentation (drf-spectacular)
# --------------------------------------------------------------------------

SPECTACULAR_SETTINGS = {
    'TITLE': 'URL Shortener API',
    'DESCRIPTION': (
        'Enterprise-Grade URL Shortener Microservice — Module 7: Auth & RBAC. '
        'JWT authentication with role-based access control (Free / Premium / Admin).'
    ),
    'VERSION': '2.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}


# --------------------------------------------------------------------------
# Internationalisation
# --------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = 'static/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
