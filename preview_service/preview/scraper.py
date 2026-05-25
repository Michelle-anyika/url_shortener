"""
URL metadata scraper.

Extracts title, description, and favicon from any public web page.
Uses httpx for HTTP and html.parser (stdlib) to avoid heavy dependencies.
"""

import logging
import httpx
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Maximum bytes to read before giving up (avoids downloading huge pages)
MAX_BYTES = 512 * 1024  # 512 KB


class MetaParser(HTMLParser):
    """Lightweight HTML parser — extracts <title> and <meta> tags only."""

    def __init__(self):
        super().__init__()
        self.title: str | None = None
        self.description: str | None = None
        self.favicon: str | None = None
        self._in_title = False
        self._title_buf: list[str] = []
        self._done = False  # stop parsing after </head>

    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        attr_dict = dict(attrs)

        if tag == 'title':
            self._in_title = True

        elif tag == 'meta':
            name = (attr_dict.get('name') or '').lower()
            prop = (attr_dict.get('property') or '').lower()
            content = attr_dict.get('content', '')

            if name == 'description' and not self.description:
                self.description = content
            elif prop == 'og:description' and not self.description:
                self.description = content
            elif prop == 'og:title' and not self.title:
                self.title = content

        elif tag == 'link':
            rel = (attr_dict.get('rel') or '').lower()
            if 'icon' in rel and not self.favicon:
                self.favicon = attr_dict.get('href', '')

    def handle_data(self, data):
        if self._in_title:
            self._title_buf.append(data)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False
            if self._title_buf and not self.title:
                self.title = ''.join(self._title_buf).strip()
            self._title_buf = []
        elif tag == 'head':
            self._done = True


def scrape(url: str, timeout: int = 10) -> dict:
    """
    Fetch `url` and extract metadata.
    Returns a dict with title, description, favicon (all nullable).
    Never raises — returns partial data on any error.
    """
    result = {'title': None, 'description': None, 'favicon': None}

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (compatible; URLShortener-PreviewBot/1.0; '
            '+https://github.com/url-shortener)'
        ),
        'Accept': 'text/html,application/xhtml+xml',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            limits=httpx.Limits(max_connections=10),
        ) as client:
            response = client.get(url)
            response.raise_for_status()

            content_type = response.headers.get('content-type', '')
            if 'html' not in content_type:
                logger.info('Non-HTML content type for %s: %s', url, content_type)
                return result

            # Read only up to MAX_BYTES to handle huge pages efficiently
            html = response.text[:MAX_BYTES]

        parser = MetaParser()
        parser.feed(html)

        result['title'] = parser.title
        result['description'] = parser.description

        # Resolve relative favicon URLs to absolute
        if parser.favicon:
            if parser.favicon.startswith(('http://', 'https://', '//')):
                result['favicon'] = parser.favicon
            else:
                result['favicon'] = urljoin(url, parser.favicon)
        else:
            # Fallback: try the standard /favicon.ico path
            parsed = urlparse(url)
            result['favicon'] = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    except httpx.TimeoutException:
        logger.warning('Scrape timeout for %s', url)
    except httpx.HTTPStatusError as e:
        logger.warning('HTTP %s for %s', e.response.status_code, url)
    except Exception as exc:
        logger.error('Scrape error for %s: %s', url, exc)

    return result
