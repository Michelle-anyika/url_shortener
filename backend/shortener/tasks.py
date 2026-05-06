from celery import shared_task
from .models import URL, Click
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def track_click_task(self, url_id, ip_address, user_agent, city, country, referrer):
    try:
        Click.objects.create(
            url_id=url_id,
            ip_address=ip_address,
            user_agent=user_agent,
            city=city,
            country=country,
            referrer=referrer
        )
    except Exception as exc:
        logger.error(f"Failed to track click for URL ID {url_id}", extra={
            'url_id': url_id,
            'error': str(exc)
        })
        raise self.retry(exc=exc)

@shared_task
def clean_expired_urls_task():
    now = timezone.now()
    # Find active URLs that have expired and deactivate them
    expired = URL.objects.filter(expires_at__lte=now, is_active=True)
    count = expired.update(is_active=False)
    logger.info(f"Cleaned up expired URLs", extra={
        'cleaned_count': count
    })
    return count
