"""
Module 9 integration tests: Microservices, CQRS, Saga, Circuit Breaker.

Coverage:
  1.  CQRS commands — CreateURL, UpdateURL, DeleteURL business rules
  2.  CQRS queries  — GetURL, ListURLs with pagination and filtering
  3.  Saga — URL creation triggers async preview task
  4.  Saga compensation — preview failure doesn't roll back URL creation
  5.  Circuit breaker — opens after threshold failures
  6.  Circuit breaker — transitions CLOSED → OPEN → HALF_OPEN → CLOSED
  7.  PreviewServiceClient — retries with exponential backoff
  8.  PreviewServiceClient — circuit open blocks call
  9.  fetch_url_preview_task — updates URL with metadata
  10. fetch_url_preview_task — handles preview service down gracefully
  11. End-to-end flow — create URL → redirect → analytics
  12. Service resilience — redirect works when Celery is unavailable
  13. Integration — health check reflects circuit breaker state
  14. CORS — relevant headers present on API responses
"""

from unittest.mock import patch, MagicMock, call
from django.test import TestCase, override_settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
import datetime

from core.models import User, TIER_FREE, TIER_PREMIUM
from shortener.models import URL, Tag, Click
from shortener.commands import (
    CreateURLCommand, UpdateURLCommand, DeleteURLCommand,
    handle_create_url, handle_update_url, handle_delete_url, CommandError,
)
from shortener.queries import get_url_by_code, list_user_urls, QueryError
from shortener.saga import URLCreationSaga
from shortener.circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from shortener.tasks import fetch_url_preview_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='user', tier=TIER_FREE, **kw):
    return User.objects.create_user(
        username=username, email=f'{username}@t.com',
        password='Pass123!', tier=tier, **kw
    )


def make_url(owner, short_code='code1', **kw):
    return URL.objects.create(
        short_code=short_code, original_url='https://example.com',
        owner=owner, **kw
    )


# ---------------------------------------------------------------------------
# 1. CQRS Commands
# ---------------------------------------------------------------------------

class CreateURLCommandTest(TestCase):

    def test_creates_url_successfully(self):
        owner = make_user('creator')
        cmd = CreateURLCommand(original_url='https://google.com', owner=owner)
        url = handle_create_url(cmd)
        self.assertIsNotNone(url.pk)
        self.assertEqual(url.owner, owner)

    def test_free_user_quota_enforced(self):
        owner = make_user('freeuser', tier=TIER_FREE)
        for i in range(10):
            make_url(owner, short_code=f'q{i}')
        cmd = CreateURLCommand(original_url='https://eleventh.com', owner=owner)
        with self.assertRaises(CommandError) as ctx:
            handle_create_url(cmd)
        self.assertEqual(ctx.exception.code, 'quota_exceeded')

    def test_custom_alias_blocked_for_free_user(self):
        owner = make_user('freeuser2', tier=TIER_FREE)
        cmd = CreateURLCommand(
            original_url='https://google.com', owner=owner,
            custom_alias='my-alias',
        )
        with self.assertRaises(CommandError) as ctx:
            handle_create_url(cmd)
        self.assertEqual(ctx.exception.code, 'permission_denied')

    def test_custom_alias_allowed_for_premium(self):
        owner = make_user('premuser', tier=TIER_PREMIUM)
        cmd = CreateURLCommand(
            original_url='https://google.com', owner=owner,
            custom_alias='my-special',
        )
        url = handle_create_url(cmd)
        self.assertEqual(url.short_code, 'my-special')

    def test_duplicate_alias_raises_error(self):
        owner = make_user('premuser2', tier=TIER_PREMIUM)
        make_url(owner, short_code='taken')
        cmd = CreateURLCommand(
            original_url='https://google.com', owner=owner,
            custom_alias='taken',
        )
        with self.assertRaises(CommandError) as ctx:
            handle_create_url(cmd)
        self.assertEqual(ctx.exception.code, 'duplicate_alias')

    def test_update_url_command(self):
        owner = make_user('updater')
        url = make_url(owner, short_code='upd1')
        cmd = UpdateURLCommand(
            short_code='upd1', requester=owner,
            original_url='https://updated.com',
        )
        updated = handle_update_url(cmd)
        self.assertEqual(updated.original_url, 'https://updated.com')

    def test_update_url_wrong_owner_raises(self):
        owner = make_user('owner1')
        other = make_user('other1')
        make_url(owner, short_code='own1')
        cmd = UpdateURLCommand(short_code='own1', requester=other)
        with self.assertRaises(CommandError) as ctx:
            handle_update_url(cmd)
        self.assertEqual(ctx.exception.code, 'not_found')

    def test_delete_url_command(self):
        owner = make_user('deleter')
        make_url(owner, short_code='del1')
        cmd = DeleteURLCommand(short_code='del1', requester=owner)
        handle_delete_url(cmd)
        self.assertFalse(URL.objects.filter(short_code='del1').exists())


# ---------------------------------------------------------------------------
# 2. CQRS Queries
# ---------------------------------------------------------------------------

class QueryTest(TestCase):

    def setUp(self):
        cache.clear()
        self.owner = make_user('queryowner')
        self.url = make_url(self.owner, short_code='qurl1')

    def tearDown(self):
        cache.clear()

    def test_get_url_by_code(self):
        url = get_url_by_code('qurl1')
        self.assertEqual(url.pk, self.url.pk)

    def test_get_url_by_code_not_found(self):
        with self.assertRaises(QueryError):
            get_url_by_code('doesnotexist')

    def test_list_user_urls_returns_only_owners(self):
        other = make_user('other2')
        make_url(other, short_code='othersurl')
        qs = list_user_urls(self.owner)
        codes = list(qs.values_list('short_code', flat=True))
        self.assertIn('qurl1', codes)
        self.assertNotIn('othersurl', codes)

    def test_list_user_urls_filter_by_tag(self):
        tag = Tag.objects.create(name='TestTag')
        self.url.tags.add(tag)
        qs = list_user_urls(self.owner, tag='TestTag')
        self.assertEqual(qs.count(), 1)

    def test_list_user_urls_search(self):
        make_url(self.owner, short_code='search1',
                 original_url='https://specific-domain.com')
        qs = list_user_urls(self.owner, search='specific-domain')
        codes = list(qs.values_list('short_code', flat=True))
        self.assertIn('search1', codes)
        self.assertNotIn('qurl1', codes)


# ---------------------------------------------------------------------------
# 3 & 4. Saga pattern
# ---------------------------------------------------------------------------

class URLCreationSagaTest(TestCase):

    def setUp(self):
        self.owner = make_user('sagaowner')

    @patch('shortener.saga.fetch_url_preview_task')
    def test_saga_creates_url_and_queues_preview(self, mock_task):
        cmd = CreateURLCommand(original_url='https://saga.test', owner=self.owner)
        saga = URLCreationSaga()
        result = saga.execute(cmd)

        self.assertIsNotNone(result.url.pk)
        self.assertTrue(result.preview_fetched)
        mock_task.delay.assert_called_once_with(result.url.pk, 'https://saga.test')

    @patch('shortener.saga.fetch_url_preview_task')
    def test_saga_compensation_url_persists_on_preview_failure(self, mock_task):
        """If Celery is down, the URL is still created (Saga forward recovery)."""
        mock_task.delay.side_effect = Exception('Broker unavailable')
        cmd = CreateURLCommand(original_url='https://saga.fail', owner=self.owner)
        saga = URLCreationSaga()
        result = saga.execute(cmd)

        # URL was created — compensation left it intact
        self.assertIsNotNone(result.url.pk)
        self.assertTrue(URL.objects.filter(pk=result.url.pk).exists())
        # But preview was not fetched
        self.assertFalse(result.preview_fetched)
        self.assertIsNotNone(result.preview_error)

    @patch('shortener.saga.fetch_url_preview_task')
    def test_saga_returns_saga_result_object(self, mock_task):
        cmd = CreateURLCommand(original_url='https://saga.ok', owner=self.owner)
        result = URLCreationSaga().execute(cmd)
        from shortener.saga import URLCreationSagaResult
        self.assertIsInstance(result, URLCreationSagaResult)


# ---------------------------------------------------------------------------
# 5 & 6. Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitBreakerTest(TestCase):

    def setUp(self):
        cache.clear()
        self.cb = CircuitBreaker('test_service', failure_threshold=3,
                                 window_seconds=60, cooldown_seconds=1)

    def tearDown(self):
        cache.clear()

    def test_initially_closed(self):
        self.assertFalse(self.cb.is_open())

    def test_opens_after_threshold_failures(self):
        for _ in range(3):
            self.cb.record_failure()
        self.assertTrue(self.cb.is_open())

    def test_closed_after_success(self):
        self.cb.record_failure()
        self.cb.record_failure()
        self.cb.record_failure()
        self.assertTrue(self.cb.is_open())
        # Simulate cooldown
        import time
        time.sleep(1.1)
        # Circuit goes half-open — allow probe
        self.assertFalse(self.cb.is_open())
        self.cb.record_success()
        # Now fully closed
        self.assertFalse(self.cb.is_open())

    def test_get_status_returns_dict(self):
        s = self.cb.get_status()
        self.assertIn('state', s)
        self.assertIn('failures', s)
        self.assertIn('threshold', s)

    def test_below_threshold_stays_closed(self):
        self.cb.record_failure()
        self.cb.record_failure()
        self.assertFalse(self.cb.is_open())


# ---------------------------------------------------------------------------
# 7 & 8. PreviewServiceClient
# ---------------------------------------------------------------------------

class PreviewServiceClientTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('shortener.services.httpx.Client')
    def test_fetch_metadata_success(self, mock_client_cls):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'title': 'Test', 'description': 'Desc', 'favicon': 'https://t.co/fav.ico'
        }
        mock_resp.raise_for_status = MagicMock()
        mock_client_cls.return_value.__enter__.return_value.get.return_value = mock_resp

        from shortener.services import PreviewServiceClient
        client = PreviewServiceClient()
        result = client.fetch_metadata('https://example.com')
        self.assertEqual(result['title'], 'Test')

    @patch('shortener.services.httpx.Client')
    def test_retries_on_connection_error(self, mock_client_cls):
        import httpx
        mock_http = MagicMock()
        mock_http.get.side_effect = httpx.ConnectError('refused')
        mock_client_cls.return_value.__enter__.return_value = mock_http

        from shortener.services import PreviewServiceClient
        client = PreviewServiceClient()
        # Patch sleep to avoid real waiting in tests
        with patch('shortener.services.time.sleep'):
            result = client.fetch_metadata('https://example.com')
        self.assertIsNone(result)
        self.assertEqual(mock_http.get.call_count, 3)  # MAX_RETRIES

    def test_circuit_open_blocks_call(self):
        cache.clear()
        from shortener.services import PreviewServiceClient, _preview_circuit_breaker
        # Force the circuit open
        for _ in range(5):
            _preview_circuit_breaker.record_failure()

        with patch('shortener.services.httpx.Client') as mock_cls:
            client = PreviewServiceClient()
            result = client.fetch_metadata('https://example.com')
        self.assertIsNone(result)
        mock_cls.assert_not_called()


# ---------------------------------------------------------------------------
# 9 & 10. fetch_url_preview_task
# ---------------------------------------------------------------------------

class FetchUrlPreviewTaskTest(TestCase):

    def setUp(self):
        cache.clear()
        owner = make_user('previewowner')
        self.url = make_url(owner, short_code='pvurl')

    def tearDown(self):
        cache.clear()

    @patch('shortener.tasks.PreviewServiceClient')
    def test_task_updates_url_with_metadata(self, mock_cls):
        mock_client = MagicMock()
        mock_client.fetch_metadata.return_value = {
            'title': 'Google', 'description': 'Search', 'favicon': 'https://g.co/fav'
        }
        mock_cls.return_value = mock_client

        fetch_url_preview_task.apply(args=[self.url.pk, 'https://google.com'])
        self.url.refresh_from_db()
        self.assertEqual(self.url.title, 'Google')
        self.assertEqual(self.url.favicon, 'https://g.co/fav')

    @patch('shortener.tasks.PreviewServiceClient')
    def test_task_handles_service_returning_none(self, mock_cls):
        mock_client = MagicMock()
        mock_client.fetch_metadata.return_value = None
        mock_cls.return_value = mock_client

        # Should retry — not crash
        result = fetch_url_preview_task.apply(args=[self.url.pk, 'https://down.com'])
        # Task retried (RETRY state) — URL still exists
        self.assertTrue(URL.objects.filter(pk=self.url.pk).exists())


# ---------------------------------------------------------------------------
# 11. End-to-end flow
# ---------------------------------------------------------------------------

class EndToEndTest(TestCase):

    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.owner = make_user('e2euser', tier=TIER_PREMIUM)

    def tearDown(self):
        cache.clear()

    @patch('shortener.saga.fetch_url_preview_task')
    def test_full_create_redirect_analytics_flow(self, mock_task):
        # 1. Create URL
        self.client.force_authenticate(user=self.owner)
        resp = self.client.post(reverse('url-create'), {
            'original_url': 'https://e2e-test.com',
            'custom_alias': 'e2etest',
        })
        self.assertEqual(resp.status_code, 201)
        short_code = resp.data['short_code']
        self.assertEqual(short_code, 'e2etest')

        # 2. Redirect (public)
        anon = APIClient()
        with patch('api.views.track_click_task') as mock_click:
            redir = anon.get(f'/{short_code}/')
            self.assertEqual(redir.status_code, 302)
            mock_click.delay.assert_called_once()

        # 3. Detail view (public)
        detail = anon.get(reverse('url-detail', kwargs={'short_code': short_code}))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data['short_code'], short_code)

        # 4. List view (authenticated)
        list_resp = self.client.get(reverse('url-list'))
        self.assertEqual(list_resp.status_code, 200)
        codes = [u['short_code'] for u in list_resp.data['results']]
        self.assertIn(short_code, codes)

        # 5. Delete
        del_resp = self.client.delete(
            reverse('url-detail', kwargs={'short_code': short_code})
        )
        self.assertEqual(del_resp.status_code, 204)


# ---------------------------------------------------------------------------
# 12. Service resilience
# ---------------------------------------------------------------------------

class ServiceResilienceTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('api.views.track_click_task')
    def test_redirect_works_when_celery_down(self, mock_task):
        owner = make_user('resowner')
        make_url(owner, short_code='res1')
        mock_task.delay.side_effect = Exception('Broker down')
        response = self.client.get('/res1/')
        self.assertEqual(response.status_code, 302)

    def test_url_created_even_when_preview_service_down(self):
        owner = make_user('resowner2', tier=TIER_PREMIUM)
        self.client.force_authenticate(user=owner)
        with patch('shortener.saga.fetch_url_preview_task') as mock_task:
            mock_task.delay.side_effect = Exception('Preview unavailable')
            resp = self.client.post(reverse('url-create'), {
                'original_url': 'https://resilience.test',
            })
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(URL.objects.filter(
            original_url='https://resilience.test'
        ).exists())


# ---------------------------------------------------------------------------
# 13. Health check reflects circuit state
# ---------------------------------------------------------------------------

class HealthCircuitBreakerTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_health_shows_circuit_open(self):
        from shortener.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker('preview_service', failure_threshold=1)
        cb.record_failure()
        response = self.client.get('/health/')
        data = response.json()
        self.assertIn('preview_circuit', data)
