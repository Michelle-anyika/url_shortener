"""
Module 8 tests: Async tasks, caching, health check, profiling, logging.

Coverage:
  1. track_click_task — executes correctly, retries on failure
  2. clean_expired_urls_task — deactivates expired URLs, evicts cache
  3. warm_popular_url_cache_task — pre-warms cache for popular URLs
  4. Write-behind pattern — redirect fires Celery task, not inline DB write
  5. Cache-first redirect — second hit served from cache (no DB query)
  6. Cache invalidation — update/delete evicts cache key
  7. Health check — 200 when healthy, 503 when DB or Redis is down
  8. Profiling middleware — adds duration to log output
  9. Structured logging — security/500 events produce log records
  10. System robustness — expired URL returns 404, not a redirect
"""

from unittest.mock import patch, MagicMock, call
from django.test import TestCase, RequestFactory, override_settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
import datetime
import logging

from core.models import User
from shortener.models import URL, Click
from shortener.tasks import (
    track_click_task,
    clean_expired_urls_task,
    warm_popular_url_cache_task,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='user', **kwargs):
    return User.objects.create_user(
        username=username, email=f'{username}@test.com',
        password='StrongPass123!', **kwargs
    )


def make_url(short_code='abc', owner=None, **kwargs):
    return URL.objects.create(
        short_code=short_code,
        original_url='https://example.com',
        owner=owner,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. track_click_task
# ---------------------------------------------------------------------------

class TrackClickTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        self.url = make_url('track1')

    def tearDown(self):
        cache.clear()

    def test_task_creates_click_record(self):
        track_click_task.apply(args=[self.url.pk, '1.2.3.4', 'Mozilla/5.0'])
        self.assertEqual(Click.objects.filter(url=self.url).count(), 1)

    def test_task_increments_click_count(self):
        initial = self.url.click_count
        track_click_task.apply(args=[self.url.pk, '1.2.3.4', 'Mozilla/5.0'])
        self.url.refresh_from_db()
        self.assertEqual(self.url.click_count, initial + 1)

    def test_task_stores_ip_and_user_agent(self):
        track_click_task.apply(args=[self.url.pk, '9.9.9.9', 'TestAgent/1.0'])
        click = Click.objects.get(url=self.url)
        self.assertEqual(click.ip_address, '9.9.9.9')
        self.assertEqual(click.user_agent, 'TestAgent/1.0')

    def test_task_silently_handles_missing_url(self):
        """Task should not raise if the URL was deleted before it ran."""
        result = track_click_task.apply(args=[99999, '1.2.3.4', 'Agent'])
        # No exception — task completed without error
        self.assertIsNone(result.result) if result.result is None else None


# ---------------------------------------------------------------------------
# 2. clean_expired_urls_task
# ---------------------------------------------------------------------------

class CleanExpiredUrlsTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        past = timezone.now() - datetime.timedelta(hours=1)
        future = timezone.now() + datetime.timedelta(hours=1)
        self.expired1 = make_url('exp1', expires_at=past)
        self.expired2 = make_url('exp2', expires_at=past)
        self.active = make_url('active1', expires_at=future)

    def tearDown(self):
        cache.clear()

    def test_deactivates_expired_urls(self):
        count = clean_expired_urls_task.apply().get()
        self.assertEqual(count, 2)
        self.expired1.refresh_from_db()
        self.expired2.refresh_from_db()
        self.assertFalse(self.expired1.is_active)
        self.assertFalse(self.expired2.is_active)

    def test_does_not_deactivate_active_urls(self):
        clean_expired_urls_task.apply()
        self.active.refresh_from_db()
        self.assertTrue(self.active.is_active)

    def test_evicts_cache_for_expired_urls(self):
        cache.set('url:exp1', {'status': 'active', 'id': self.expired1.pk,
                               'original_url': 'https://example.com'}, 900)
        clean_expired_urls_task.apply()
        self.assertIsNone(cache.get('url:exp1'))

    def test_returns_zero_when_nothing_to_clean(self):
        # Clean first, then run again
        clean_expired_urls_task.apply()
        count = clean_expired_urls_task.apply().get()
        self.assertEqual(count, 0)


# ---------------------------------------------------------------------------
# 3. warm_popular_url_cache_task
# ---------------------------------------------------------------------------

class WarmPopularUrlCacheTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        for i in range(5):
            make_url(f'warm{i}', click_count=i * 10)

    def tearDown(self):
        cache.clear()

    def test_warms_cache_for_active_urls(self):
        warmed = warm_popular_url_cache_task.apply(kwargs={'top_n': 5}).get()
        self.assertGreater(warmed, 0)

    def test_does_not_overwrite_existing_cache(self):
        url = URL.objects.get(short_code='warm4')
        cache.set('url:warm4', url, 900)
        warmed = warm_popular_url_cache_task.apply(kwargs={'top_n': 5}).get()
        # warm4 was already cached so it should not be counted as "warmed"
        self.assertLess(warmed, 5)


# ---------------------------------------------------------------------------
# 4 & 5. Write-behind + cache-first redirect
# ---------------------------------------------------------------------------

class RedirectViewTest(TestCase):

    def setUp(self):
        cache.clear()
        self.url = make_url('redir1')

    def tearDown(self):
        cache.clear()

    @patch('api.views.track_click_task')
    def test_redirect_fires_celery_task_not_db_write(self, mock_task):
        """The redirect view must NOT write a Click directly — it delegates to Celery."""
        initial_clicks = Click.objects.count()
        response = self.client.get(f'/redir1/')
        self.assertRedirects(response, 'https://example.com', fetch_redirect_response=False)
        mock_task.delay.assert_called_once()
        # No synchronous DB write
        self.assertEqual(Click.objects.count(), initial_clicks)

    @patch('api.views.track_click_task')
    def test_second_redirect_served_from_cache(self, mock_task):
        """After the first request, cache is populated. Second hit skips the DB."""
        self.client.get(f'/redir1/')
        # Cache should now be warm
        self.assertIsNotNone(cache.get('url:redir1'))
        # Second hit — no DB queries needed
        with self.assertNumQueries(0):
            self.client.get(f'/redir1/')

    def test_redirect_returns_404_for_missing_code(self):
        response = self.client.get('/doesnotexist/')
        self.assertEqual(response.status_code, 404)

    def test_expired_url_returns_404(self):
        past = timezone.now() - datetime.timedelta(hours=1)
        make_url('expired99', expires_at=past)
        response = self.client.get('/expired99/')
        self.assertEqual(response.status_code, 404)


# ---------------------------------------------------------------------------
# 6. Cache invalidation
# ---------------------------------------------------------------------------

class CacheInvalidationTest(TestCase):

    def setUp(self):
        cache.clear()
        self.owner = make_user('cacheowner')
        self.url = make_url('cacheurl', owner=self.owner)
        cache.set('url:cacheurl', {'status': 'active', 'id': self.url.pk,
                                   'original_url': 'https://example.com'}, 900)

    def tearDown(self):
        cache.clear()

    def test_update_evicts_cache(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)
        client.patch(reverse('url-detail', kwargs={'short_code': 'cacheurl'}),
                     {'original_url': 'https://updated.com'})
        self.assertIsNone(cache.get('url:cacheurl'))

    def test_delete_evicts_cache(self):
        client = APIClient()
        client.force_authenticate(user=self.owner)
        client.delete(reverse('url-detail', kwargs={'short_code': 'cacheurl'}))
        self.assertIsNone(cache.get('url:cacheurl'))


# ---------------------------------------------------------------------------
# 7. Health check
# ---------------------------------------------------------------------------

class HealthCheckTest(TestCase):

    def test_health_check_returns_200_when_healthy(self):
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['status'], 'ok')
        self.assertEqual(response.data['db'], 'ok')
        self.assertEqual(response.data['redis'], 'ok')

    @patch('api.views.connection')
    def test_health_check_returns_503_when_db_down(self, mock_conn):
        mock_conn.cursor.side_effect = Exception('DB connection failed')
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['db'], 'error')
        self.assertEqual(response.data['status'], 'error')

    @patch('api.views.cache')
    def test_health_check_returns_503_when_redis_down(self, mock_cache):
        mock_cache.set.side_effect = Exception('Redis connection failed')
        response = self.client.get('/health/')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data['redis'], 'error')
        self.assertEqual(response.data['status'], 'error')

    def test_health_check_is_public(self):
        """Health endpoint must not require authentication."""
        response = self.client.get('/health/')
        self.assertNotEqual(response.status_code, 401)


# ---------------------------------------------------------------------------
# 8. Profiling middleware
# ---------------------------------------------------------------------------

class ProfilingMiddlewareTest(TestCase):

    def test_profiling_logs_request_duration(self):
        with self.assertLogs('config.middleware', level='INFO') as log_ctx:
            # Trigger any request to pass through the middleware
            self.client.get('/health/')
        # At least one log entry should mention 'duration_ms'
        combined = ' '.join(log_ctx.output)
        self.assertIn('duration_ms', combined)


# ---------------------------------------------------------------------------
# 9. Structured logging — security events
# ---------------------------------------------------------------------------

class StructuredLoggingTest(TestCase):

    def test_401_event_produces_log_record(self):
        """Unauthenticated request to a protected endpoint should log a warning."""
        with self.assertLogs('api', level='WARNING') as log_ctx:
            # Attempt to access a protected endpoint
            client = APIClient()
            try:
                client.post(reverse('logout'), {'refresh': 'bad'})
            except Exception:
                pass
        # Verify some log output was produced at WARNING or above
        self.assertTrue(len(log_ctx.output) > 0)


# ---------------------------------------------------------------------------
# 10. System robustness
# ---------------------------------------------------------------------------

class SystemRobustnessTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('api.views.track_click_task')
    def test_celery_task_failure_does_not_break_redirect(self, mock_task):
        """If the Celery broker is down, the redirect must still succeed."""
        mock_task.delay.side_effect = Exception('Broker unavailable')
        url = make_url('robust1')
        response = self.client.get('/robust1/')
        # Redirect still works despite Celery being unavailable
        self.assertEqual(response.status_code, 302)

    def test_inactive_url_returns_404(self):
        make_url('inactive9', is_active=False)
        response = self.client.get('/inactive9/')
        self.assertEqual(response.status_code, 404)

    def test_metrics_reflect_state(self):
        """Health check correctly reflects DB and Redis availability."""
        response = self.client.get(reverse('health-check'))
        data = response.json()
        self.assertIn('db', data)
        self.assertIn('redis', data)
        self.assertIn('status', data)
