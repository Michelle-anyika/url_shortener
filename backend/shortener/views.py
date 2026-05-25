import string
import random

from django.db import transaction
from django.core.cache import cache
from django.http import JsonResponse, HttpResponseRedirect
from django.views import View
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator

from .models import URL, Click, Tag

CACHE_TTL = 60 * 15  # 15 minutes


def _generate_short_code(length=6):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


class ShortenURLView(View):
    """
    POST /shorten/
    Creates a new short URL inside an atomic transaction so that the URL
    record and any tag associations are committed together or not at all.
    """

    @method_decorator(transaction.atomic)
    def post(self, request):
        import json
        try:
            data = json.loads(request.body)
        except (ValueError, KeyError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        original_url = data.get('original_url', '').strip()
        if not original_url:
            return JsonResponse({'error': 'original_url is required'}, status=400)

        custom_alias = data.get('custom_alias', '').strip() or None
        tag_names = data.get('tags', [])

        # Generate a unique short code
        for _ in range(10):
            short_code = custom_alias or _generate_short_code()
            if not URL.objects.filter(short_code=short_code).exists():
                break
        else:
            return JsonResponse({'error': 'Could not generate unique short code'}, status=500)

        # All DB writes happen inside the atomic block (decorated at method level)
        url = URL.objects.create(
            original_url=original_url,
            short_code=short_code,
            custom_alias=custom_alias,
            owner=request.user if request.user.is_authenticated else None,
            expires_at=data.get('expires_at'),
            title=data.get('title'),
            description=data.get('description'),
        )

        if tag_names:
            tags = Tag.objects.filter(name__in=tag_names)
            url.tags.set(tags)

        # Invalidate any stale cache entry for this code
        cache.delete(f'url:{short_code}')

        return JsonResponse({
            'short_code': url.short_code,
            'original_url': url.original_url,
            'short_url': f"/r/{url.short_code}",
        }, status=201)


class RedirectView(View):
    """
    GET /r/<short_code>/
    Looks up the URL (cache-first), records a Click, and redirects.
    The click log write is in its own atomic block so a logging failure
    never breaks the redirect.
    """

    def get(self, request, short_code):
        cache_key = f'url:{short_code}'
        url = cache.get(cache_key)

        if url is None:
            try:
                url = URL.objects.active_urls().get(short_code=short_code)
                cache.set(cache_key, url, CACHE_TTL)
            except URL.DoesNotExist:
                return JsonResponse({'error': 'URL not found or expired'}, status=404)

        # Log the click atomically — failure here should not affect the redirect
        try:
            with transaction.atomic():
                Click.objects.create(
                    url=url,
                    ip_address=_get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    referrer=request.META.get('HTTP_REFERER', '') or None,
                )
                URL.objects.filter(pk=url.pk).update(
                    click_count=url.click_count + 1
                )
        except Exception:
            pass  # Never let analytics logging block a redirect

        return HttpResponseRedirect(url.original_url)


class URLStatsView(View):
    """
    GET /stats/<short_code>/
    Returns analytics for a URL: click count, clicks per country.
    Uses DB-level aggregation (annotate + values) — no Python-level looping.
    """

    def get(self, request, short_code):
        try:
            url = URL.objects.with_click_stats().get(short_code=short_code)
        except URL.DoesNotExist:
            return JsonResponse({'error': 'URL not found'}, status=404)

        clicks_by_country = list(
            Click.objects.clicks_per_country(url.pk)
        )

        return JsonResponse({
            'short_code': url.short_code,
            'original_url': url.original_url,
            'click_count': url.click_count,
            'total_clicks_recorded': url.total_clicks_recorded,
            'clicks_by_country': clicks_by_country,
            'tags': list(url.tags.values_list('name', flat=True)),
        })


class DeactivateURLView(View):
    """
    POST /deactivate/<short_code>/
    Deactivates a URL and immediately evicts it from cache, all atomically.
    """

    @method_decorator(transaction.atomic)
    def post(self, request, short_code):
        try:
            url = URL.objects.select_for_update().get(short_code=short_code)
        except URL.DoesNotExist:
            return JsonResponse({'error': 'URL not found'}, status=404)

        url.is_active = False
        url.save(update_fields=['is_active'])

        # Evict from cache inside the same transaction boundary
        cache.delete(f'url:{short_code}')

        return JsonResponse({'status': 'deactivated', 'short_code': short_code})


def _get_client_ip(request):
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
