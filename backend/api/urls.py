from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from api.views import (
    UserRegisterView,
    ThrottledTokenObtainPairView,
    LogoutView,
    SocialAuthView,
    URLCreateView,
    URLListView,
    URLDetailView,
    URLAnalyticsView,
)

urlpatterns = [
    # --- Authentication ---
    path('auth/register/', UserRegisterView.as_view(), name='register'),
    path('auth/login/',    ThrottledTokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('auth/refresh/',  TokenRefreshView.as_view(), name='token_refresh'),
    path('auth/logout/',   LogoutView.as_view(), name='logout'),
    path('auth/social/',   SocialAuthView.as_view(), name='social_auth'),

    # --- URL management ---
    path('urls/',               URLCreateView.as_view(), name='url-create'),
    path('urls/list/',          URLListView.as_view(),   name='url-list'),
    path('urls/<str:short_code>/', URLDetailView.as_view(), name='url-detail'),

    # --- Analytics (Premium only) ---
    path('analytics/<str:short_code>/', URLAnalyticsView.as_view(), name='url-analytics'),
]
