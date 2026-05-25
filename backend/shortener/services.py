"""
Domain Services — external HTTP communication layer.

PreviewServiceClient
  Calls the Preview Microservice to fetch URL metadata.
  Implements: retries with exponential backoff + circuit breaker.
"""

import logging
import time
import httpx
from django.conf import settings
from shortener.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
INITIAL_WAIT = 1.0   # seconds
BACKOFF_FACTOR = 2   # exponential: 1s, 2s, 4s

# One shared circuit breaker for the preview service
_preview_circuit_breaker = CircuitBreaker('preview_service')


class PreviewServiceClient:
    """
    HTTP client for the Preview Microservice.

    Resilience features:
      1. Exponential backoff retries (up to MAX_RETRIES attempts)
      2. Circuit breaker — stops calling after repeated failures,
         auto-recovers after cooldown
    """

    def __init__(self):
        self.base_url = getattr(
            settings, 'PREVIEW_SERVICE_URL',
            'http://preview_service:8001',
        )
        self.timeout = getattr(settings, 'PREVIEW_SERVICE_TIMEOUT', 10)
        self.circuit_breaker = _preview_circuit_breaker

    def fetch_metadata(self, url: str) -> dict | None:
        """
        Call the preview service and return metadata dict, or None on failure.
        Never raises — callers can safely ignore the return value.
        """
        if self.circuit_breaker.is_open():
            logger.warning(
                'Circuit breaker OPEN — skipping preview fetch',
                extra={'url': url, **self.circuit_breaker.get_status()},
            )
            return None

        endpoint = f"{self.base_url}/api/preview/"
        last_exc = None
        wait = INITIAL_WAIT

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    response = client.get(endpoint, params={'url': url})
                    response.raise_for_status()
                    result = response.json()
                    self.circuit_breaker.record_success()
                    logger.info(
                        'Preview fetched successfully',
                        extra={'url': url, 'attempt': attempt},
                    )
                    return result

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                self.circuit_breaker.record_failure()
                logger.warning(
                    'Preview service unreachable (attempt %d/%d)',
                    attempt, MAX_RETRIES,
                    extra={'url': url, 'error': str(exc)},
                )

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                # 4xx errors are not retriable
                if exc.response.status_code < 500:
                    logger.warning(
                        'Preview service returned %d — not retrying',
                        exc.response.status_code,
                        extra={'url': url},
                    )
                    return None
                self.circuit_breaker.record_failure()
                logger.warning(
                    'Preview service server error %d (attempt %d/%d)',
                    exc.response.status_code, attempt, MAX_RETRIES,
                    extra={'url': url},
                )

            except Exception as exc:
                last_exc = exc
                self.circuit_breaker.record_failure()
                logger.error(
                    'Unexpected preview service error (attempt %d/%d)',
                    attempt, MAX_RETRIES,
                    extra={'url': url, 'error': str(exc)},
                )

            if attempt < MAX_RETRIES:
                logger.info('Retrying in %.1fs...', wait)
                time.sleep(wait)
                wait *= BACKOFF_FACTOR  # exponential backoff

        logger.error(
            'Preview fetch failed after %d attempts',
            MAX_RETRIES,
            extra={'url': url, 'last_error': str(last_exc)},
        )
        return None
