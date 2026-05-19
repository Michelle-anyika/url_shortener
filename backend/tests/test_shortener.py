import pytest
from rest_framework.test import APIClient
from shortener.models import URL

@pytest.fixture
def api_client():
    return APIClient()

def test_create_short_url(api_client):
    response = api_client.post('/api/urls/', {'original_url': 'https://www.example.com'})
    assert response.status_code == 201
    assert 'short_code' in response.data
    assert URL.objects.count() == 1
    
def test_create_invalid_url(api_client):
    response = api_client.post('/api/urls/', {'original_url': 'not-a-url'})
    assert response.status_code == 400

def test_redirect_short_url(api_client):
    # First create one directly in DB
    url = URL.objects.create(original_url='https://www.example.com', short_code='abcdef')
    
    response = api_client.get('/abcdef/')
    assert response.status_code == 302
    assert response.url == 'https://www.example.com'
