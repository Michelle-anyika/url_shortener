"""
Preview Microservice — API views.

GET  /api/preview/?url=<target_url>   — returns title, description, favicon
GET  /health/                          — liveness probe
"""

import logging
from django.conf import settings
from django.http import JsonResponse
from django.views import View

from preview.scraper import scrape

logger = logging.getLogger(__name__)


class PreviewView(View):
    """
    Synchronous preview endpoint.

    Query params:
      url (required) — the destination URL to scrape

    Response 200:
      { "title": "...", "description": "...", "favicon": "..." }

    Response 400:
      { "error": "url parameter is required" }

    Response 500:
      { "error": "...", "title": null, "description": null, "favicon": null }
    """

    def get(self, request):
        target_url = request.GET.get('url', '').strip()
        if not target_url:
            return JsonResponse({'error': 'url parameter is required'}, status=400)

        if not target_url.startswith(('http://', 'https://')):
            return JsonResponse({'error': 'url must start with http:// or https://'}, status=400)

        timeout = getattr(settings, 'SCRAPER_TIMEOUT', 10)
        logger.info('Scraping preview', extra={'url': target_url})

        result = scrape(target_url, timeout=timeout)

        logger.info(
            'Preview scraped',
            extra={'url': target_url, 'has_title': bool(result['title'])},
        )
        return JsonResponse(result)


class HealthView(View):
    """Liveness probe — always returns 200 if the process is up."""

    def get(self, request):
        return JsonResponse({'status': 'ok', 'service': 'preview'})
