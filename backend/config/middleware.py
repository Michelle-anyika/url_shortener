"""
Custom middleware stack for URL Shortener.

SecurityHeadersMiddleware  — injects HTTP security headers on every response
ProfilingMiddleware        — logs request timing in JSON for performance monitoring
"""

import time
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware:
    """Injects security headers on every HTTP response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=(), payment=()'
        response['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "connect-src 'self';"
        )
        response['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response


class ProfilingMiddleware:
    """
    Measures wall-clock time for every request and emits a structured
    JSON log entry.

    Fields logged:
      method       — HTTP method
      path         — request path
      status_code  — HTTP response status
      duration_ms  — time from request start to response in milliseconds
      slow_request — True if duration > SLOW_REQUEST_THRESHOLD_MS

    Slow requests (>500ms by default) are logged at WARNING level so they
    appear as actionable items in monitoring dashboards.
    """

    SLOW_REQUEST_THRESHOLD_MS = 500

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        duration_ms = round((time.monotonic() - start) * 1000, 2)

        is_slow = duration_ms > self.SLOW_REQUEST_THRESHOLD_MS
        log_fn = logger.warning if is_slow else logger.info

        log_fn(
            'Request profiled',
            extra={
                'method': request.method,
                'path': request.path,
                'status_code': response.status_code,
                'duration_ms': duration_ms,
                'slow_request': is_slow,
            },
        )
        return response
