import httpx
from bs4 import BeautifulSoup
from django.http import JsonResponse
from django.views.decorators.http import require_GET
import logging

logger = logging.getLogger(__name__)

@require_GET
def preview_view(request):
    target_url = request.GET.get('url')
    if not target_url:
        return JsonResponse({'error': 'URL parameter is required'}, status=400)

    try:
        # Use httpx to fetch the page content
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            response = client.get(target_url)
            response.raise_for_status()
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract title
        title = soup.title.string if soup.title else None
        if not title:
            title = soup.find('meta', property='og:title')
            title = title['content'] if title else None
            
        # Extract description
        description = None
        desc_meta = soup.find('meta', attrs={'name': 'description'})
        if desc_meta:
            description = desc_meta.get('content')
        if not description:
            desc_meta = soup.find('meta', property='og:description')
            description = desc_meta.get('content') if desc_meta else None
            
        # Extract favicon
        favicon = None
        icon_link = soup.find('link', rel=lambda x: x and 'icon' in x.lower())
        if icon_link:
            favicon = icon_link.get('href')
            # Handle relative URLs
            if favicon and not favicon.startswith(('http://', 'https://')):
                from urllib.parse import urljoin
                favicon = urljoin(target_url, favicon)
        
        return JsonResponse({
            'title': title.strip() if title else None,
            'description': description.strip() if description else None,
            'favicon': favicon,
        })

    except Exception as e:
        logger.error(f"Failed to fetch preview for {target_url}: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch preview metadata'}, status=500)
