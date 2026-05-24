from django.urls import path
from api.views import URLCreateView
from shortener.factories import URLServiceFactory

# Instantiate concrete service instance using the factory
url_service = URLServiceFactory.create_service()

urlpatterns = [
    # Inject service dependency into the class-based view via properties
    path('urls/', URLCreateView.as_view(service=url_service), name='url-create'),
]
