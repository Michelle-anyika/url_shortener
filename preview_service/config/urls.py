from django.urls import path
from preview.views import PreviewView, HealthView

urlpatterns = [
    path('api/preview/', PreviewView.as_view(), name='preview'),
    path('health/', HealthView.as_view(), name='health'),
]
