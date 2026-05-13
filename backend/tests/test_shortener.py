import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework import status
from shortener.models import URL
from core.models import User

@pytest.fixture
def api_client():
    return APIClient()

@pytest.fixture
def authenticated_client(db):
    client = APIClient()
    user = User.objects.create_user(username='testuser', password='password123', email='test@example.com')
    client.force_authenticate(user=user)
    return client

@pytest.fixture
def premium_user(db):
    user = User.objects.create_user(
        username='premiumuser', 
        password='password123', 
        email='premium@example.com',
        tier='Premium'
    )
    return user

@pytest.fixture
def premium_client(db, premium_user):
    client = APIClient()
    client.force_authenticate(user=premium_user)
    return client

@pytest.mark.django_db
def test_create_short_url(authenticated_client):
    url = reverse('url-create')
    response = authenticated_client.post(url, {'original_url': 'https://www.example.com'})
    assert response.status_code == 201
    assert 'short_code' in response.data
    assert URL.objects.count() == 1
    
@pytest.mark.django_db
def test_create_invalid_url(authenticated_client):
    url = reverse('url-create')
    response = authenticated_client.post(url, {'original_url': 'not-a-url'})
    assert response.status_code == 400

@pytest.mark.django_db
def test_redirect_short_url(api_client):
    # First create one directly in DB
    url = URL.objects.create(original_url='https://www.example.com', short_code='abcdef')
    
    # Redirect view is public, so no auth needed
    response = api_client.get('/abcdef/')
    assert response.status_code == 302
    assert response.url == 'https://www.example.com'

@pytest.mark.django_db
def test_free_user_quota_limit(authenticated_client):
    url = reverse('url-create')
    # Create 10 URLs to reach limit
    for i in range(10):
        response = authenticated_client.post(url, {'original_url': f'https://example{i}.com'})
        assert response.status_code == 201
    
    # 11th should fail
    response = authenticated_client.post(url, {'original_url': 'https://example11.com'})
    assert response.status_code == 400
    assert 'Free tier allows a maximum of 10 active URLs' in str(response.data)

@pytest.mark.django_db
def test_premium_custom_alias(premium_client):
    url = reverse('url-create')
    response = premium_client.post(url, {
        'original_url': 'https://www.example.com',
        'custom_alias': 'my-custom-link'
    })
    assert response.status_code == 201
    assert response.data['short_code'] == 'my-custom-link'

@pytest.mark.django_db
def test_free_user_cannot_use_custom_alias(authenticated_client):
    url = reverse('url-create')
    response = authenticated_client.post(url, {
        'original_url': 'https://www.example.com',
        'custom_alias': 'my-link'
    })
    assert response.status_code == 400
    assert 'Custom aliases are a Premium feature' in str(response.data)

@pytest.mark.django_db
def test_analytics_requires_premium(authenticated_client):
    # Create a URL
    url_obj = URL.objects.create(
        original_url='https://www.example.com', 
        short_code='testcode',
        owner=authenticated_client.handler._force_user
    )
    url = reverse('url-analytics', kwargs={'short_code': 'testcode'})
    response = authenticated_client.get(url)
    assert response.status_code == 403  # Forbidden for non-premium

@pytest.mark.django_db
def test_analytics_for_premium_user(premium_client, premium_user):
    # Create a URL
    url_obj = URL.objects.create(
        original_url='https://www.example.com', 
        short_code='testcode',
        owner=premium_user
    )
    url = reverse('url-analytics', kwargs={'short_code': 'testcode'})
    response = premium_client.get(url)
    assert response.status_code == 200
    assert 'country_breakdown' in response.data

@pytest.mark.django_db
def test_url_owner_permissions(authenticated_client):
    # Create URL for this user
    url_obj = URL.objects.create(
        original_url='https://www.example.com', 
        short_code='mycode',
        owner=authenticated_client.handler._force_user
    )
    
    # Try to access another user's URL
    other_user = User.objects.create_user(username='other', password='pass', email='other@example.com')
    other_url = URL.objects.create(
        original_url='https://www.other.com', 
        short_code='othercode',
        owner=other_user
    )
    
    url = reverse('url-detail', kwargs={'short_code': 'othercode'})
    response = authenticated_client.get(url)
    assert response.status_code == 404  # Should not see other's URLs
