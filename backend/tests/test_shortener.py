import pytest
from unittest.mock import MagicMock
from rest_framework.test import APIClient
from rest_framework import status
from django.shortcuts import get_object_or_404
from shortener.models import URL
from shortener.services import URLService, BaseURLService
from shortener.factories import URLServiceFactory, ShortCodeGeneratorFactory
from api.views import URLCreateView, URLRedirectView

@pytest.fixture
def api_client():
    return APIClient()

# ==========================================
# 1. CORE FUNCTIONAL TESTS
# ==========================================

def test_create_short_url_success(api_client):
    """Test successful short URL creation with valid inputs."""
    response = api_client.post('/api/urls/', {'original_url': 'https://www.google.com'})
    assert response.status_code == status.HTTP_201_CREATED
    assert 'short_code' in response.data
    assert len(response.data['short_code']) == 6
    assert URL.objects.count() == 1

def test_create_url_invalid_format(api_client):
    """Test validator rejects malformed URLs."""
    response = api_client.post('/api/urls/', {'original_url': 'not-a-valid-url'})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'original_url' in response.data

def test_create_url_invalid_scheme(api_client):
    """Test validator rejects URLs without http:// or https://."""
    response = api_client.post('/api/urls/', {'original_url': 'ftp://ftp.example.com'})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'original_url' in response.data
    assert "URL must start with http:// or https://" in response.data['original_url'][0]

def test_redirect_url_success(api_client):
    """Test redirection to original URL works correctly."""
    url = URL.objects.create(original_url='https://www.github.com', short_code='git123')
    response = api_client.get('/git123/')
    assert response.status_code == status.HTTP_302_FOUND
    assert response.url == 'https://www.github.com'

def test_redirect_url_not_found(api_client):
    """Test redirection returns 404 for a non-existent short code."""
    response = api_client.get('/nonexist/')
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.data['detail'] == 'Short URL not found.'


# ==========================================
# 2. DEPENDENCY INJECTION (DI) TESTS
# ==========================================

def test_view_uses_injected_service_on_post():
    """Verify that URLCreateView relies on the injected service interface."""
    # Arrange
    mock_service = MagicMock(spec=BaseURLService)
    created_url = URL(original_url='https://injected.com', short_code='inj123')
    mock_service.create_short_url.return_value = created_url
    
    view = URLCreateView()
    view.service = mock_service
    
    # Fake DRF Request
    client = APIClient()
    request = client.post('/api/urls/', {'original_url': 'https://injected.com'}, format='json')
    request.data = {'original_url': 'https://injected.com'}
    
    # Act
    response = view.post(request)
    
    # Assert
    assert response.status_code == status.HTTP_201_CREATED
    mock_service.create_short_url.assert_called_once_with('https://injected.com')
    assert response.data['short_code'] == 'inj123'

def test_view_uses_injected_service_on_get():
    """Verify that URLRedirectView relies on the injected service interface."""
    # Arrange
    mock_service = MagicMock(spec=BaseURLService)
    url_obj = URL(original_url='https://redirect-inj.com', short_code='red123')
    mock_service.get_url_by_code.return_value = url_obj
    
    view = URLRedirectView()
    view.service = mock_service
    
    # Act
    response = view.get(None, 'red123')
    
    # Assert
    mock_service.get_url_by_code.assert_called_once_with('red123')
    assert response.status_code == status.HTTP_302_FOUND
    assert response.url == 'https://redirect-inj.com'

def test_service_code_generator_injection():
    """Verify constructor injection of code generator inside URLService."""
    # Arrange
    mock_generator = MagicMock(return_value="mocked")
    service = URLService(code_generator=mock_generator)
    
    # Act
    url_obj = service.create_short_url("https://generator-inj.com")
    
    # Assert
    mock_generator.assert_called_once()
    assert url_obj.short_code == "mocked"
    assert url_obj.original_url == "https://generator-inj.com"


# ==========================================
# 3. FACTORY PATTERN TESTS
# ==========================================

def test_url_service_factory():
    """Test URLServiceFactory creates active URLService instances."""
    service = URLServiceFactory.create_service()
    assert isinstance(service, URLService)
    assert service.code_generator == ShortCodeGeneratorFactory.get_generator("default")

def test_short_code_generator_factory():
    """Test ShortCodeGeneratorFactory returns generator functions or raises error."""
    generator = ShortCodeGeneratorFactory.get_generator("default")
    assert callable(generator)
    
    # Assert generator works as expected
    code = generator()
    assert len(code) == 6
    
    # Assert invalid type raises ValueError
    with pytest.raises(ValueError):
        ShortCodeGeneratorFactory.get_generator("invalid-type")
