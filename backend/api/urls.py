from django.urls import path
from api.views import URLCreateView

urlpatterns = [
    path('urls/', URLCreateView.as_view(), name='url-create'),
]
