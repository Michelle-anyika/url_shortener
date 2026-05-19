from django.urls import path, include

urlpatterns = [
    path('api/preview/', include('preview.urls')),
]
