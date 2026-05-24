from abc import ABC, abstractmethod
from shortener.models import URL
from shortener.utils import generate_short_code

class BaseURLService(ABC):
    @abstractmethod
    def create_short_url(self, original_url: str) -> URL:
        """
        Create a new short URL for the given original URL.
        """
        pass

    @abstractmethod
    def get_url_by_code(self, short_code: str) -> URL:
        """
        Retrieve the URL instance matching the short_code.
        """
        pass

class URLService(BaseURLService):
    def __init__(self, code_generator=None):
        """
        Constructor injection for the short code generator logic.
        """
        self.code_generator = code_generator or generate_short_code

    def create_short_url(self, original_url: str) -> URL:
        # Generate unique short code
        while True:
            code = self.code_generator()
            if not URL.objects.filter(short_code=code).exists():
                break
        
        return URL.objects.create(original_url=original_url, short_code=code)

    def get_url_by_code(self, short_code: str) -> URL:
        try:
            return URL.objects.get(short_code=short_code)
        except URL.DoesNotExist:
            return None
