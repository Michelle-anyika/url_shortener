from django.urls import path
from .views import preview_view

urlpatterns = [
    path('', preview_view, name='preview'),
]
