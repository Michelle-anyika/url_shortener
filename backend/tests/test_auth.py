import pytest
from django.urls import reverse
from rest_framework import status
from core.models import User
from shortener.models import URL

@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()

@pytest.fixture
def create_user(db):
    def make_user(**kwargs):
        return User.objects.create_user(**kwargs)
    return make_user

@pytest.mark.django_db
class TestAuthentication:
    def test_user_registration(self, api_client):
        url = reverse('register')
        data = {
            "username": "newuser",
            "email": "new@example.com",
            "password": "password123"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert User.objects.filter(username="newuser").exists()

    def test_jwt_login(self, api_client, create_user):
        create_user(username="testuser", password="password123", email="test@example.com")
        url = reverse('token_obtain_pair')
        data = {
            "username": "testuser",
            "password": "password123"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_200_OK
        assert "access" in response.data
        assert "refresh" in response.data

@pytest.mark.django_db
class TestRBACAndQuotas:
    def test_unauthorized_url_creation(self, api_client):
        url = reverse('url-create')
        data = {"original_url": "https://google.com"}
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_free_user_quota_limit(self, api_client, create_user):
        user = create_user(username="freeuser", password="password123", tier="Free", email="free@test.com")
        api_client.force_authenticate(user=user)
        
        # Create 10 URLs
        for i in range(10):
            URL.objects.create(original_url=f"https://site{i}.com", short_code=f"code{i}", owner=user)
        
        # Attempt 11th creation
        url = reverse('url-create')
        data = {"original_url": "https://site11.com"}
        response = api_client.post(url, data)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Free tier allows a maximum of 10 active URLs" in str(response.data)

    def test_free_user_custom_alias_restriction(self, api_client, create_user):
        user = create_user(username="freeuser2", password="password123", tier="Free", email="free2@test.com")
        api_client.force_authenticate(user=user)
        
        url = reverse('url-create')
        data = {
            "original_url": "https://google.com",
            "custom_alias": "my-google"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Custom aliases are a Premium feature" in str(response.data)

    def test_premium_user_custom_alias_allowed(self, api_client, create_user):
        user = create_user(username="premuser", password="password123", tier="Premium", email="prem@test.com")
        api_client.force_authenticate(user=user)
        
        url = reverse('url-create')
        data = {
            "original_url": "https://google.com",
            "custom_alias": "my-special-link"
        }
        response = api_client.post(url, data)
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['short_code'] == "my-special-link"

@pytest.mark.django_db
class TestOwnership:
    def test_owner_can_update_url(self, api_client, create_user):
        user = create_user(username="owner", password="password123", email="owner@test.com")
        url_obj = URL.objects.create(original_url="https://a.com", short_code="acode", owner=user)
        
        api_client.force_authenticate(user=user)
        url = reverse('url-detail', kwargs={'short_code': 'acode'})
        data = {"original_url": "https://b.com"}
        response = api_client.patch(url, data)
        assert response.status_code == status.HTTP_200_OK
        url_obj.refresh_from_db()
        assert url_obj.original_url == "https://b.com"

    def test_other_user_cannot_update_url(self, api_client, create_user):
        owner = create_user(username="owner2", password="password123", email="owner2@test.com")
        other = create_user(username="other", password="password123", email="other@test.com")
        URL.objects.create(original_url="https://a.com", short_code="acode2", owner=owner)
        
        api_client.force_authenticate(user=other)
        url = reverse('url-detail', kwargs={'short_code': 'acode2'})
        data = {"original_url": "https://evil.com"}
        response = api_client.patch(url, data)
        assert response.status_code == status.HTTP_403_FORBIDDEN
