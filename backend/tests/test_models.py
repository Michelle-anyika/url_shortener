import pytest
from django.utils import timezone
from datetime import timedelta
from shortener.models import URL, Tag, Click
from core.models import User

@pytest.mark.django_db
def test_url_manager_active_expired():
    user = User.objects.create(username='testuser', email='test@test.com')
    tag = Tag.objects.create(name='TestTag')
    
    url_active1 = URL.objects.create(original_url='http://a.com', short_code='a', owner=user)
    url_active1.tags.add(tag)
    url_active2 = URL.objects.create(original_url='http://b.com', short_code='b', expires_at=timezone.now() + timedelta(days=1))
    url_expired = URL.objects.create(original_url='http://c.com', short_code='c', expires_at=timezone.now() - timedelta(days=1))
    url_inactive = URL.objects.create(original_url='http://d.com', short_code='d', is_active=False)

    active_urls = URL.objects.active_urls()
    expired_urls = URL.objects.expired_urls()

    assert url_active1 in active_urls
    assert url_active2 in active_urls
    assert url_expired not in active_urls
    assert url_inactive not in active_urls

    assert url_expired in expired_urls
    assert url_active1 not in expired_urls

@pytest.mark.django_db
def test_url_manager_optimized(django_assert_num_queries):
    user1 = User.objects.create(username='user1', email='1@test.com')
    user2 = User.objects.create(username='user2', email='2@test.com')
    
    for i in range(5):
        URL.objects.create(original_url=f'http://{i}.com', short_code=f's{i}', owner=user1 if i % 2 == 0 else user2)
    
    # N+1 test
    with django_assert_num_queries(2): # 1 for URL, 1 for prefetch tags
        urls = list(URL.objects.optimized())
        for url in urls:
            # Should not cause extra queries
            _ = url.owner.username if url.owner else None
            _ = list(url.tags.all())

@pytest.mark.django_db
def test_click_country_stats():
    url = URL.objects.create(original_url='http://a.com', short_code='a')
    Click.objects.create(url=url, country='USA')
    Click.objects.create(url=url, country='USA')
    Click.objects.create(url=url, country='Canada')
    Click.objects.create(url=url, country=None)

    stats = list(Click.objects.clicks_per_country(url.id))
    
    assert len(stats) == 3
    
    # Asserting correct counts and ordering
    assert stats[0] == {'country': 'USA', 'total': 2}
    assert stats[1]['total'] == 1
    assert stats[2]['total'] == 1
