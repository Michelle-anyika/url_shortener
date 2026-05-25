"""
Celery tasks for the shortener app.

Write-Behind Pattern
--------------------
Instead of writing Click records synchronously inside the HTTP request
(which adds DB latency to every redirect), the redirect view fires
track_click_task.delay(...) and returns the redirect immediately.
The task runs in a background worker and persists the analytics data
without the user ever waiting for it.

Periodic Tasks (Beat)
---------------------
clean_expired_urls_task  — runs nightly at midnight (configured in celery.py)
warm_popular_url_cache_task — runs every 6 hours to pre-warm popular URLs
"""

import logging
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 15  # 15 minutes


# ---------------------------------------------------------------------------
# Write-Behind: Click tracking
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    name='shortener.tasks.track_click_task',
)
def track_click_task(self, url_id, ip_address, user_agent, referrer=None,
                     city=None, country=None):
    """
    Persist a Click record asynchronously.

    Called by the redirect view via .delay() so the user gets their
    redirect instantly without waiting for a DB write.

    Retries up to 3 times with a 5-second delay if the DB is unavailable.
    """
    from shortener.models import Click, URL

    try:
        url = URL.objects.get(pk=url_id)
        Click.objects.create(
            url=url,
            ip_address=ip_address or None,
            user_agent=user_agent or '',
            referrer=referrer or None,
            city=city or '',
            country=country or '',
        )
        # Atomically increment the denormalised counter
        URL.objects.filter(pk=url_id).update(
            click_count=url.click_count + 1
        )
        logger.info(
            'Click tracked successfully',
            extra={'url_id': url_id, 'ip': ip_address},
        )
    except URL.DoesNotExist:
        # URL was deleted between the redirect and the task running — ignore
        logger.warning('track_click_task: URL %s not found, skipping', url_id)
    except Exception as exc:
        logger.error(
            'track_click_task failed, retrying',
            extra={'url_id': url_id, 'error': str(exc)},
        )
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Periodic: Expire stale URLs
# ---------------------------------------------------------------------------

@shared_task(
    name='shortener.tasks.clean_expired_urls_task',
)
def clean_expired_urls_task():
    """
    Nightly cleanup task (Celery Beat — runs at midnight UTC).

    Finds all URLs whose expires_at has passed and marks them inactive.
    Also evicts their cache keys so stale data is not served.

    Returns the number of URLs deactivated (logged for monitoring).
    """
    from shortener.models import URL

    now = timezone.now()
    expired_qs = URL.objects.filter(expires_at__lte=now, is_active=True)

    # Collect short codes before the update so we can evict cache
    short_codes = list(expired_qs.values_list('short_code', flat=True))

    count = expired_qs.update(is_active=False)

    # Evict cache for every deactivated URL
    for code in short_codes:
        cache.delete(f'url:{code}')

    logger.info(
        'clean_expired_urls_task completed',
        extra={'deactivated_count': count},
    )
    return count


# ---------------------------------------------------------------------------
# Periodic: Cache warming
# ---------------------------------------------------------------------------

@shared_task(
    name='shortener.tasks.warm_popular_url_cache_task',
)
def warm_popular_url_cache_task(top_n=100):
    """
    Cache-warming task (Celery Beat — runs every 6 hours).

    Pre-loads the top N most-clicked active URLs into Redis so the first
    request after a cache miss never hits the database.
    This is especially useful after a Redis restart.
    """
    from shortener.models import URL

    popular = URL.objects.active_urls().popular()[:top_n]
    warmed = 0
    for url in popular:
        cache_key = f'url:{url.short_code}'
        if cache.get(cache_key) is None:
            cache.set(cache_key, url, CACHE_TTL)
            warmed += 1

    logger.info(
        'warm_popular_url_cache_task completed',
        extra={'checked': len(popular), 'warmed': warmed},
    )
    return warmed
