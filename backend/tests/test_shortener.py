import pytest
from django.urls import reverse
from rest_framework.test import APIClient
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
