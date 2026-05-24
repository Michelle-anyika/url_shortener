"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from api.views import URLRedirectView
from shortener.factories import URLServiceFactory

# Instantiate concrete service instance using the factory
url_service = URLServiceFactory.create_service()

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    
    # Swagger docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    
    # Redirect endpoint (using the Class-Based View with dependency injection)
    path('<str:short_code>/', URLRedirectView.as_view(service=url_service), name='redirect-view'),
]
