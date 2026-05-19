import pytest
from unittest.mock import patch, MagicMock
from shortener.models import URL
from shortener.tasks import fetch_url_preview_task
from shortener.services import PreviewService

@pytest.mark.django_db
class TestModule9:
    @patch('shortener.services.PreviewService.fetch_metadata')
    def test_fetch_url_preview_task_success(self, mock_fetch, user):
        # Create a URL object
        url_obj = URL.objects.create(
            original_url="https://google.com",
            short_code="goog",
            owner=user
        )
        
        # Mock the preview service response
        mock_fetch.return_value = {
            'title': 'Google',
            'description': 'Search the world\'s information',
            'favicon': 'https://google.com/favicon.ico'
        }
        
        # Run the task synchronously
        fetch_url_preview_task(url_obj.id)
        
        # Refresh from DB and verify
        url_obj.refresh_from_db()
        assert url_obj.title == 'Google'
        assert url_obj.description == 'Search the world\'s information'
        assert url_obj.favicon == 'https://google.com/favicon.ico'

    @patch('httpx.Client.get')
    def test_preview_service_retry_logic(self, mock_get):
        # Mock a failing response then a success
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'title': 'Success'}
        mock_response.raise_for_status = MagicMock()
        
        mock_get.side_effect = [Exception("Transient error"), mock_response]
        
        # This should succeed due to retries
        result = PreviewService.fetch_metadata("https://example.com")
        assert result['title'] == 'Success'
        assert mock_get.call_count == 2
