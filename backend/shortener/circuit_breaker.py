"""
Redis-backed Circuit Breaker for external HTTP calls.

States
------
CLOSED   — normal operation; requests pass through
OPEN     — too many failures; requests are rejected immediately
HALF_OPEN — cooldown expired; one probe request is allowed through

Transitions
-----------
CLOSED → OPEN       : failure_count >= FAILURE_THRESHOLD within WINDOW_SECONDS
OPEN   → HALF_OPEN  : COOLDOWN_SECONDS have elapsed
HALF_OPEN → CLOSED  : probe request succeeded
HALF_OPEN → OPEN    : probe request failed

Usage
-----
    cb = CircuitBreaker('preview_service')
    if cb.is_open():
        raise CircuitBreakerOpenError("Circuit is open for preview_service")
    try:
        result = call_external_service()
        cb.record_success()
    except Exception:
        cb.record_failure()
        raise
"""

import time
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Tuneable thresholds
FAILURE_THRESHOLD = 5      # open after this many failures
WINDOW_SECONDS = 300       # sliding window: 5 minutes
COOLDOWN_SECONDS = 30      # wait before allowing a probe in HALF_OPEN


class CircuitBreakerOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""


class CircuitBreaker:
    """
    Per-service circuit breaker backed by Redis.

    Each instance is namespaced by `service_name` so you can have independent
    breakers for different downstream services.
    """

    STATE_CLOSED = 'closed'
    STATE_OPEN = 'open'
    STATE_HALF_OPEN = 'half_open'

    def __init__(
        self,
        service_name: str,
        failure_threshold: int = FAILURE_THRESHOLD,
        window_seconds: int = WINDOW_SECONDS,
        cooldown_seconds: int = COOLDOWN_SECONDS,
    ):
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds

        self._key_state = f'cb:{service_name}:state'
        self._key_failures = f'cb:{service_name}:failures'
        self._key_opened_at = f'cb:{service_name}:opened_at'

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_open(self) -> bool:
        """Return True if the circuit should block the call."""
        state = self._get_state()
        if state == self.STATE_CLOSED:
            return False
        if state == self.STATE_OPEN:
            if self._cooldown_elapsed():
                self._transition(self.STATE_HALF_OPEN)
                logger.info('Circuit breaker HALF-OPEN for %s', self.service_name)
                return False   # allow one probe through
            return True
        # HALF_OPEN — let one call through
        return False

    def record_success(self):
        """Call this after a successful downstream request."""
        state = self._get_state()
        if state in (self.STATE_HALF_OPEN, self.STATE_OPEN):
            self._reset()
            logger.info('Circuit breaker CLOSED for %s (recovered)', self.service_name)

    def record_failure(self):
        """Call this after a failed downstream request."""
        failures = self._increment_failures()
        state = self._get_state()

        if state == self.STATE_HALF_OPEN:
            # Probe failed — reopen immediately
            self._transition(self.STATE_OPEN)
            logger.warning('Circuit breaker re-OPENED for %s (probe failed)', self.service_name)
            return

        if failures >= self.failure_threshold and state == self.STATE_CLOSED:
            self._transition(self.STATE_OPEN)
            cache.set(self._key_opened_at, time.time(), timeout=self.window_seconds * 2)
            logger.warning(
                'Circuit breaker OPENED for %s after %d failures',
                self.service_name, failures,
            )

    def get_status(self) -> dict:
        """Return current circuit state for monitoring / health checks."""
        return {
            'service': self.service_name,
            'state': self._get_state(),
            'failures': int(cache.get(self._key_failures) or 0),
            'threshold': self.failure_threshold,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self) -> str:
        return cache.get(self._key_state) or self.STATE_CLOSED

    def _transition(self, new_state: str):
        cache.set(self._key_state, new_state, timeout=self.window_seconds * 2)

    def _increment_failures(self) -> int:
        try:
            return cache.incr(self._key_failures)
        except ValueError:
            cache.set(self._key_failures, 1, timeout=self.window_seconds)
            return 1

    def _cooldown_elapsed(self) -> bool:
        opened_at = cache.get(self._key_opened_at)
        if opened_at is None:
            return True
        return (time.time() - float(opened_at)) >= self.cooldown_seconds

    def _reset(self):
        cache.delete(self._key_state)
        cache.delete(self._key_failures)
        cache.delete(self._key_opened_at)
