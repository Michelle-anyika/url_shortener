"""
CQRS — Query Side.

Queries are read-only operations. They never modify state.
All DB reads in the application go through query functions.

Query functions use optimized querysets (select_related, prefetch_related,
annotate) so callers never trigger N+1 queries.

Queries
-------
get_url_by_code     — single URL lookup (used by redirect + detail views)
list_user_urls      — paginated list of a user's active URLs
get_url_analytics   — URL with aggregated click stats
search_urls_by_tag  — filter URLs by tag name
"""

from typing import Optional
from django.db.models import QuerySet
from shortener.models import URL, Click
from core.models import User


class QueryError(Exception):
    """Raised when a query cannot be satisfied (e.g. not found)."""
    def __init__(self, message: str, code: str = 'query_error'):
        self.message = message
        self.code = code
        super().__init__(message)


def get_url_by_code(short_code: str) -> URL:
    """
    Fetch a single active URL by short_code.
    Uses select_related to avoid N+1 on owner access.
    Raises QueryError if not found.
    """
    try:
        return URL.objects.active_urls().get(short_code=short_code)
    except URL.DoesNotExist:
        raise QueryError(f"URL '{short_code}' not found.", code='not_found')


def list_user_urls(
    owner: User,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> QuerySet:
    """
    Return a queryset of the user's active URLs, optionally filtered.
    Always uses optimized() to prevent N+1.

    Supports:
      tag    — filter by tag name (exact match)
      search — filter original_url or short_code (case-insensitive contains)
    """
    qs = URL.objects.active_urls().filter(owner=owner)

    if tag:
        qs = qs.filter(tags__name__iexact=tag)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(original_url__icontains=search) |
            Q(short_code__icontains=search) |
            Q(title__icontains=search)
        )

    return qs.distinct()


def get_url_analytics(short_code: str, owner: User) -> URL:
    """
    Fetch a URL with aggregated click stats.
    Restricted to the owner (used by premium analytics endpoint).
    Raises QueryError if not found or not owned.
    """
    try:
        return URL.objects.with_click_stats().get(
            short_code=short_code,
            owner=owner,
        )
    except URL.DoesNotExist:
        raise QueryError(
            f"URL '{short_code}' not found or you do not own it.",
            code='not_found',
        )


def get_clicks_by_country(url: URL) -> list:
    """Return click aggregation by country for the given URL."""
    return list(Click.objects.clicks_per_country(url.pk))
