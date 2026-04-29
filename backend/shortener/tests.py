import pytest
from django.db import IntegrityError
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from shortener.models import URL, Tag, Click
from core.models import User

@pytest.fixture
def user():
    return User.objects.create_user(username='testuser', email='test@example.com', password='password123')

@pytest.mark.django_db
class TestShortenerModels:
    def test_create_tag(self):
        tag = Tag.objects.create(name='Marketing')
        assert tag.name == 'Marketing'
        assert str(tag) == 'Marketing'

    def test_tag_name_unique(self):
        Tag.objects.create(name='UniqueTag')
        with pytest.raises(IntegrityError):
            Tag.objects.create(name='UniqueTag')

    def test_create_url_with_defaults(self):
        url = URL.objects.create(original_url='https://example.com', short_code='abcde')
        assert url.is_active is True
        assert url.click_count == 0
        assert url.owner is None
        assert url.created_at is not None
        assert url.title is None
        assert url.description is None
        assert url.favicon is None
        assert url.custom_alias is None
        assert url.expires_at is None

    def test_create_url_with_owner_and_metadata(self, user):
        url = URL.objects.create(
            original_url='https://example.com/long',
            short_code='fghij',
            owner=user,
            title='Example Site',
            description='A site for examples',
            favicon='https://example.com/favicon.ico',
            custom_alias='example-alias'
        )
        assert url.owner == user
        assert url.title == 'Example Site'
        assert url.custom_alias == 'example-alias'

    def test_url_custom_alias_unique(self):
        URL.objects.create(original_url='https://example.com', short_code='code1', custom_alias='my-alias')
        with pytest.raises(IntegrityError):
            URL.objects.create(original_url='https://example2.com', short_code='code2', custom_alias='my-alias')

    def test_url_tags_relationship(self):
        url = URL.objects.create(original_url='https://example.com', short_code='code3')
        tag1 = Tag.objects.create(name='Social')
        tag2 = Tag.objects.create(name='News')
        url.tags.add(tag1, tag2)
        assert url.tags.count() == 2
        assert tag1 in url.tags.all()

    def test_create_click_for_url(self):
        url = URL.objects.create(original_url='https://example.com', short_code='code4')
        click = Click.objects.create(
            url=url,
            ip_address='192.168.1.1',
            city='New York',
            country='USA',
            user_agent='Mozilla/5.0',
            referrer='https://google.com'
        )
        assert click.url == url
        assert click.ip_address == '192.168.1.1'
        assert click.clicked_at is not None

    def test_click_cascade_delete(self):
        url = URL.objects.create(original_url='https://example.com', short_code='code5')
        Click.objects.create(url=url, ip_address='127.0.0.1')
        assert Click.objects.count() == 1
        url.delete()
        assert Click.objects.count() == 0

@pytest.mark.django_db
class TestURLManager:
    @pytest.fixture(autouse=True)
    def setup_data(self, user):
        self.user = user
        # Active URLs
        self.active1 = URL.objects.create(original_url='https://a.com', short_code='a', click_count=10)
        self.active2 = URL.objects.create(original_url='https://b.com', short_code='b', click_count=50)
        
        # Expired URL
        self.expired = URL.objects.create(
            original_url='https://c.com', 
            short_code='c', 
            expires_at=timezone.now() - timedelta(days=1),
            click_count=5
        )
        
        # Inactive URL
        self.inactive = URL.objects.create(original_url='https://d.com', short_code='d', is_active=False)
        
        # Future Expiry URL (still active)
        self.future_expiry = URL.objects.create(
            original_url='https://e.com', 
            short_code='e', 
            expires_at=timezone.now() + timedelta(days=1),
            click_count=100
        )

    def test_active_urls(self):
        active_urls = URL.objects.active_urls()
        assert self.active1 in active_urls
        assert self.active2 in active_urls
        assert self.future_expiry in active_urls
        assert self.expired not in active_urls
        assert self.inactive not in active_urls

    def test_expired_urls(self):
        expired_urls = URL.objects.expired_urls()
        assert self.expired in expired_urls
        assert self.active1 not in expired_urls

    def test_popular_urls(self):
        popular = list(URL.objects.popular_urls()[:3])
        # Should be ordered by click_count DESC
        assert popular == [self.future_expiry, self.active2, self.active1]

@pytest.mark.django_db
class TestQueryOptimization:
    def test_n_plus_one_owner(self, django_assert_num_queries):
        user1 = User.objects.create_user(username='u1', email='u1@example.com')
        user2 = User.objects.create_user(username='u2', email='u2@example.com')
        for i in range(5):
            URL.objects.create(original_url=f'https://u1-{i}.com', short_code=f'u1{i}', owner=user1)
            URL.objects.create(original_url=f'https://u2-{i}.com', short_code=f'u2{i}', owner=user2)
            
        # Using select_related, it should be 1 query to fetch URLs and their Owners
        with django_assert_num_queries(1):
            urls = URL.objects.select_related('owner').all()
            for url in urls:
                _ = url.owner.username

    def test_n_plus_one_tags(self, django_assert_num_queries):
        tag1 = Tag.objects.create(name='T1')
        tag2 = Tag.objects.create(name='T2')
        for i in range(5):
            url = URL.objects.create(original_url=f'https://t-{i}.com', short_code=f't{i}')
            url.tags.add(tag1, tag2)
            
        # prefetch_related should result in 2 queries (1 for URLs, 1 for Tags)
        with django_assert_num_queries(2):
            urls = URL.objects.prefetch_related('tags').all()
            for url in urls:
                _ = list(url.tags.all())
