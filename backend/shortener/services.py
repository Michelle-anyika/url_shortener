import httpx
import logging
from django.conf import settings
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

class PreviewService:
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True
    )
    def fetch_metadata(url: str):
        """
        Calls the external preview service to fetch metadata for a given URL.
        Includes retry logic with exponential backoff.
        """
        # The preview service URL will be defined in settings or environment
        # In Docker Compose, we'll use the service name 'preview_service'
        preview_service_url = getattr(settings, 'PREVIEW_SERVICE_URL', 'http://preview_service:8001/api/preview/')
        
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(preview_service_url, params={'url': url})
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Preview service returned error status {e.response.status_code} for {url}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Failed to connect to preview service: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error calling preview service: {str(e)}")
            raise
