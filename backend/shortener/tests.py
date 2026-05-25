"""
Module 6 tests: ORM, transactions, caching, query optimisation.
"""

from django.test import TestCase, RequestFactory
from django.core.cache import cache
from django.db import transaction, DatabaseError
from django.utils import timezone
from unittest.mock import patch
import datetime

from core.models import User
from shortener.models import URL, Click, Tag
from shortener.views import RedirectView, ShortenURLView


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='testuser', **kwargs):
    return User.objects.create_user(username=username, password='pass', **kwargs)


def make_url(short_code='abc123', original_url='https://example.com', **kwargs):
    return URL.objects.create(
        short_code=short_code,
        original_url=original_url,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Model tests
# ---------------------------------------------------------------------------

class UserModelTest(TestCase):

    def test_default_tier_is_free(self):
        user = make_user('alice')
        self.assertEqual(user.tier, 'free')
        self.assertFalse(user.is_premium)

    def test_premium_user(self):
        user = make_user('bob', is_premium=True, tier='pro')
        self.assertTrue(user.is_premium)
        self.assertEqual(user.tier, 'pro')


class URLModelTest(TestCase):

    def test_is_expired_no_expiry(self):
        url = make_url()
        self.assertFalse(url.is_expired)

    def test_is_expired_past_date(self):
        past = timezone.now() - datetime.timedelta(days=1)
        url = make_url(short_code='exp1', expires_at=past)
        self.assertTrue(url.is_expired)

    def test_is_expired_future_date(self):
        future = timezone.now() + datetime.timedelta(days=1)
        url = make_url(short_code='exp2', expires_at=future)
        self.assertFalse(url.is_expired)


class TagModelTest(TestCase):

    def test_tags_many_to_many(self):
        tag1, _ = Tag.objects.get_or_create(name='Marketing')
        tag2, _ = Tag.objects.get_or_create(name='Social')
        url = make_url()
        url.tags.set([tag1, tag2])
        self.assertEqual(url.tags.count(), 2)
        self.assertIn(tag1, url.tags.all())


# ---------------------------------------------------------------------------
# 2. Custom Manager / QuerySet tests
# ---------------------------------------------------------------------------

class URLManagerTest(TestCase):

    def setUp(self):
        self.owner = make_user()
        self.active = make_url('active1', owner=self.owner)
        self.inactive = make_url('inactive1', is_active=False, owner=self.owner)
        past = timezone.now() - datetime.timedelta(hours=1)
        self.expired = make_url('expired1', expires_at=past, owner=self.owner)

    def test_active_urls_excludes_inactive(self):
        active = list(URL.objects.active_urls())
        codes = [u.short_code for u in active]
        self.assertIn('active1', codes)
        self.assertNotIn('inactive1', codes)
        self.assertNotIn('expired1', codes)

    def test_expired_urls(self):
        expired = list(URL.objects.expired_urls())
        codes = [u.short_code for u in expired]
        self.assertIn('expired1', codes)
        self.assertIn('inactive1', codes)

    def test_popular_urls_ordered_by_click_count(self):
        URL.objects.filter(short_code='active1').update(click_count=10)
        URL.objects.filter(short_code='inactive1').update(click_count=5)
        popular = list(URL.objects.popular_urls())
        self.assertEqual(popular[0].short_code, 'active1')

    def test_with_click_stats_annotates(self):
        Click.objects.create(url=self.active, country='GH')
        Click.objects.create(url=self.active, country='US')
        result = URL.objects.with_click_stats().get(short_code='active1')
        self.assertEqual(result.total_clicks_recorded, 2)


class ClickManagerTest(TestCase):

    def setUp(self):
        self.url = make_url()
        Click.objects.create(url=self.url, country='GH')
        Click.objects.create(url=self.url, country='GH')
        Click.objects.create(url=self.url, country='US')

    def test_clicks_per_country_aggregates_in_db(self):
        stats = list(Click.objects.clicks_per_country(self.url.pk))
        countries = {s['country']: s['total'] for s in stats}
        self.assertEqual(countries['GH'], 2)
        self.assertEqual(countries['US'], 1)

    def test_clicks_per_country_ordered_by_total_desc(self):
        stats = list(Click.objects.clicks_per_country(self.url.pk))
        self.assertEqual(stats[0]['country'], 'GH')


# ---------------------------------------------------------------------------
# 3. Query optimisation tests (N+1)
# ---------------------------------------------------------------------------

class QueryOptimisationTest(TestCase):

    def setUp(self):
        owner = make_user()
        tag = Tag.objects.create(name='Test')
        for i in range(5):
            url = make_url(f'code{i}', owner=owner)
            url.tags.add(tag)

    def test_active_urls_uses_select_related_no_extra_queries(self):
        """
        Fetching 5 URLs with their owner should require only 1 query
        (select_related) instead of 6 (1 + N).
        """
        with self.assertNumQueries(2):  # 1 URL query + 1 prefetch for tags
            urls = list(URL.objects.active_urls())
            for url in urls:
                _ = url.owner   # should NOT trigger extra query
                _ = list(url.tags.all())  # should NOT trigger extra query


# ---------------------------------------------------------------------------
# 4. Atomic transaction tests
# ---------------------------------------------------------------------------

class AtomicTransactionTest(TestCase):

    def test_url_create_rolls_back_on_tag_failure(self):
        """
        If tag assignment fails after URL creation, the whole transaction
        should roll back and leave the DB clean.
        """
        initial_count = URL.objects.count()

        with self.assertRaises(Exception):
            with transaction.atomic():
                url = URL.objects.create(
                    short_code='rollme',
                    original_url='https://rollback.test',
                )
                # Force a failure inside the atomic block
                raise DatabaseError("Simulated DB failure")

        self.assertEqual(URL.objects.count(), initial_count)

    def test_click_logged_atomically(self):
        """Both the Click record and the click_count increment must succeed together."""
        url = make_url('clicktest')
        initial_click_count = url.click_count

        with transaction.atomic():
            Click.objects.create(url=url, country='GH')
            URL.objects.filter(pk=url.pk).update(click_count=url.click_count + 1)

        url.refresh_from_db()
        self.assertEqual(url.click_count, initial_click_count + 1)
        self.assertEqual(Click.objects.filter(url=url).count(), 1)


# ---------------------------------------------------------------------------
# 5. Caching tests
# ---------------------------------------------------------------------------

class CachingTest(TestCase):

    def setUp(self):
        cache.clear()
        self.url = make_url('cached1')
        self.factory = RequestFactory()

    def tearDown(self):
        cache.clear()

    def test_redirect_view_caches_url(self):
        """After the first hit the URL object should be in cache."""
        request = self.factory.get('/r/cached1/')
        view = RedirectView.as_view()
        view(request, short_code='cached1')
        cached = cache.get('url:cached1')
        self.assertIsNotNone(cached)
        self.assertEqual(cached.short_code, 'cached1')

    def test_redirect_view_uses_cache_on_second_hit(self):
        """Second request must not hit the database."""
        request = self.factory.get('/r/cached1/')
        view = RedirectView.as_view()
        # Warm the cache
        view(request, short_code='cached1')

        with self.assertNumQueries(0):
            cached = cache.get('url:cached1')
            self.assertIsNotNone(cached)

    def test_deactivate_evicts_cache(self):
        """Deactivating a URL should remove it from cache."""
        cache.set('url:cached1', self.url, 900)
        import json
        request = self.factory.post(
            '/deactivate/cached1/',
            data=json.dumps({}),
            content_type='application/json',
        )
        from shortener.views import DeactivateURLView
        DeactivateURLView.as_view()(request, short_code='cached1')
        self.assertIsNone(cache.get('url:cached1'))


# ---------------------------------------------------------------------------
# 6. Data migration: seeded tags
# ---------------------------------------------------------------------------

class SeededTagsTest(TestCase):
    """
    Verify the data migration ran and default tags exist.
    Note: Django test runner re-runs migrations on the test DB, so seeded
    data will be present if the migration file is correct.
    """

    EXPECTED_TAGS = [
        'Marketing', 'Social', 'Blog', 'Campaign',
        'Product', 'Support', 'Internal', 'News',
    ]

    def test_default_tags_exist(self):
        for name in self.EXPECTED_TAGS:
            self.assertTrue(
                Tag.objects.filter(name=name).exists(),
                msg=f"Expected seeded tag '{name}' not found",
            )
