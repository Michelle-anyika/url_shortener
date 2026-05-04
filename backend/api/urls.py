from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from api.views import (
    URLCreateView, UserRegisterView, URLListView, 
    URLDetailView, URLAnalyticsView, ThrottledTokenObtainPairView
)

urlpatterns = [
    # Auth
    path('auth/register/', UserRegisterView.as_view(), name='register'),
    path('auth/login/', ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # URL Operations
    path('urls/', URLCreateView.as_view(), name='url-create'),
    path('urls/list/', URLListView.as_view(), name='url-list'),
    path('urls/<str:short_code>/', URLDetailView.as_view(), name='url-detail'),
    path('analytics/<str:short_code>/', URLAnalyticsView.as_view(), name='url-analytics'),
]
