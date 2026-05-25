"""
Celery tasks — Module 8 + 9.

track_click_task         — write-behind analytics (Module 8)
clean_expired_urls_task  — nightly cleanup (Module 8)
warm_popular_url_cache_task — cache warming (Module 8)
fetch_url_preview_task   — async preview metadata fetch (Module 9)
"""

import logging
from celery import shared_task
from django.utils import timezone
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 15


# ---------------------------------------------------------------------------
# Module 8: Write-Behind click tracking
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=5,
             name='shortener.tasks.track_click_task')
def track_click_task(self, url_id, ip_address, user_agent, referrer=None,
                     city=None, country=None):
    from shortener.models import Click, URL
    try:
        url = URL.objects.get(pk=url_id)
        Click.objects.create(
            url=url, ip_address=ip_address or None,
            user_agent=user_agent or '', referrer=referrer or None,
            city=city or '', country=country or '',
        )
        URL.objects.filter(pk=url_id).update(click_count=url.click_count + 1)
        logger.info('Click tracked', extra={'url_id': url_id})
    except Exception as exc:
        logger.error('track_click_task failed', extra={'url_id': url_id, 'error': str(exc)})
        raise self.retry(exc=exc)


# ---------------------------------------------------------------------------
# Module 8: Nightly cleanup
# ---------------------------------------------------------------------------

@shared_task(name='shortener.tasks.clean_expired_urls_task')
def clean_expired_urls_task():
    from shortener.models import URL
    now = timezone.now()
    expired_qs = URL.objects.filter(expires_at__lte=now, is_active=True)
    short_codes = list(expired_qs.values_list('short_code', flat=True))
    count = expired_qs.update(is_active=False)
    for code in short_codes:
        cache.delete(f'url:{code}')
    logger.info('clean_expired_urls_task', extra={'deactivated_count': count})
    return count


# ---------------------------------------------------------------------------
# Module 8: Cache warming
# ---------------------------------------------------------------------------

@shared_task(name='shortener.tasks.warm_popular_url_cache_task')
def warm_popular_url_cache_task(top_n=100):
    from shortener.models import URL
    popular = URL.objects.active_urls().popular()[:top_n]
    warmed = sum(
        1 for url in popular
        if cache.get(f'url:{url.short_code}') is None
        and cache.set(f'url:{url.short_code}', url, CACHE_TTL) is None
    )
    logger.info('warm_popular_url_cache_task', extra={'warmed': warmed})
    return warmed


# ---------------------------------------------------------------------------
# Module 9: Async preview fetch (Saga Step 2)
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    name='shortener.tasks.fetch_url_preview_task',
)
def fetch_url_preview_task(self, url_id: int, original_url: str):
    """
    Asynchronously fetches title/description/favicon from the Preview Service
    and updates the URL record.

    This is Step 2 of the URLCreationSaga. It runs in the background so
    the HTTP response to the user is not blocked by the external HTTP call.

    Retries 3 times with 10-second delays if the preview service is down.
    """
    from shortener.models import URL
    from shortener.services import PreviewServiceClient

    try:
        url = URL.objects.get(pk=url_id)
    except URL.DoesNotExist:
        logger.warning('fetch_url_preview_task: URL %d not found', url_id)
        return

    client = PreviewServiceClient()
    metadata = client.fetch_metadata(original_url)

    if metadata:
        url.title = metadata.get('title') or url.title
        url.description = metadata.get('description') or url.description
        url.favicon = metadata.get('favicon') or url.favicon
        url.save(update_fields=['title', 'description', 'favicon'])
        logger.info(
            'Preview metadata saved',
            extra={'url_id': url_id, 'title': url.title},
        )
    else:
        # Circuit is open or service returned nothing — retry later
        logger.warning(
            'fetch_url_preview_task: no metadata returned, will retry',
            extra={'url_id': url_id},
        )
        raise self.retry(exc=Exception('Preview service returned no data'))
