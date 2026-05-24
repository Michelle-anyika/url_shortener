from shortener.services import URLService
from shortener.utils import generate_short_code

class ShortCodeGeneratorFactory:
    @staticmethod
    def get_generator(generator_type="default"):
        """
        Factory method to get a code generator function.
        Allows switching generator implementation easily (e.g., in tests).
        """
        if generator_type == "default":
            return generate_short_code
        else:
            raise ValueError(f"Unknown generator type: {generator_type}")

class URLServiceFactory:
    @staticmethod
    def create_service(generator_type="default") -> URLService:
        """
        Factory method to instantiate URLService with its dependencies resolved.
        """
        generator = ShortCodeGeneratorFactory.get_generator(generator_type)
        return URLService(code_generator=generator)
