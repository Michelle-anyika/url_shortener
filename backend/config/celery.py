"""
Celery application for URL Shortener.

Workers:
  celery -A config worker -l info

Beat scheduler (periodic tasks):
  celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

Or run both together in development:
  celery -A config worker --beat -l info
"""

import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

app = Celery('config')

# All Celery config keys must use the CELERY_ prefix (from settings.py)
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all INSTALLED_APPS
app.autodiscover_tasks()


# ---------------------------------------------------------------------------
# Celery Beat — periodic task schedule
# ---------------------------------------------------------------------------

app.conf.beat_schedule = {
    # Nightly at midnight UTC: deactivate expired URLs
    'clean-expired-urls-nightly': {
        'task': 'shortener.tasks.clean_expired_urls_task',
        'schedule': crontab(hour=0, minute=0),
        'options': {'expires': 3600},  # drop if not picked up within 1 hour
    },
    # Every 6 hours: warm the cache for the top 100 most-clicked URLs
    'warm-popular-url-cache': {
        'task': 'shortener.tasks.warm_popular_url_cache_task',
        'schedule': crontab(minute=0, hour='*/6'),
        'options': {'expires': 3600},
    },
}

app.conf.timezone = 'UTC'


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
