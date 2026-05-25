"""
API views for the URL Shortener.

Auth endpoints:
  POST /api/v1/auth/register/      — create account
  POST /api/v1/auth/login/         — obtain JWT (rate-limited: 5/min)
  POST /api/v1/auth/refresh/       — refresh access token
  POST /api/v1/auth/logout/        — blacklist refresh token
  POST /api/v1/auth/social/        — social auth (Google ID token → JWT)

URL endpoints:
  POST   /api/v1/urls/             — create (authenticated)
  GET    /api/v1/urls/             — list own URLs (authenticated)
  GET    /api/v1/urls/<code>/      — retrieve (public)
  PATCH  /api/v1/urls/<code>/      — update (owner only)
  DELETE /api/v1/urls/<code>/      — delete (owner only)
  GET    /api/v1/analytics/<code>/ — analytics (premium only + owner)
"""

import requests as http_requests
from django.shortcuts import get_object_or_404, redirect
from django.db import transaction
from django.core.cache import cache
from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from api.serializers import (
    UserRegistrationSerializer,
    UserProfileSerializer,
    URLSerializer,
    URLAnalyticsSerializer,
    SocialAuthSerializer,
)
from api.permissions import IsOwnerOrReadOnly, IsOwnerOnly, IsPremiumUser
from shortener.models import URL, Click
from core.models import User

CACHE_TTL = 60 * 15  # 15 minutes


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class UserRegisterView(generics.CreateAPIView):
    """
    POST /api/v1/auth/register/
    Open endpoint — no authentication required.
    Returns the new user's profile on success.
    """

    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        profile = UserProfileSerializer(user)
        # Issue tokens immediately so the user can start using the API
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'user': profile.data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/
    Standard JWT login with a custom throttle scope.
    Rate limit: 5 requests per minute (configured in settings.py).
    """

    throttle_scope = 'login'


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/
    Blacklists the provided refresh token, effectively logging the user out
    from all devices that used that refresh token.
    """

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'refresh token is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_200_OK)
        except TokenError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SocialAuthView(APIView):
    """
    POST /api/v1/auth/social/
    Social authentication via Google OAuth2.

    Accepts: { "provider": "google", "token": "<Google ID token>" }
    Returns: { "access": "...", "refresh": "...", "user": {...} }

    Flow:
      1. Verify the Google ID token with Google's tokeninfo endpoint.
      2. Extract the email from the verified payload.
      3. Get or create the user (matched by email).
      4. Issue a JWT pair.

    This keeps the backend stateless — no session is created.
    """

    permission_classes = [permissions.AllowAny]

    GOOGLE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'

    def post(self, request):
        serializer = SocialAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        provider = serializer.validated_data['provider']
        token = serializer.validated_data['token']

        if provider == 'google':
            user = self._authenticate_google(token)
        else:
            return Response(
                {'error': f"Provider '{provider}' is not supported."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if user is None:
            return Response(
                {'error': 'Could not verify social token. Please try again.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        refresh = RefreshToken.for_user(user)
        return Response({
            'user': UserProfileSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })

    def _authenticate_google(self, id_token):
        """
        Verify a Google ID token and return the matching User.
        Creates a new account if the email has not been seen before.
        """
        try:
            resp = http_requests.get(
                self.GOOGLE_TOKENINFO_URL,
                params={'id_token': id_token},
                timeout=5,
            )
            if resp.status_code != 200:
                return None

            payload = resp.json()
            email = payload.get('email')
            if not email or not payload.get('email_verified', False):
                return None

            user, created = User.objects.get_or_create(
                email=email,
                defaults={
                    'username': email.split('@')[0],
                    'is_active': True,
                },
            )
            return user

        except Exception:
            return None


# ---------------------------------------------------------------------------
# URL views
# ---------------------------------------------------------------------------

class URLCreateView(APIView):
    """
    POST /api/v1/urls/
    Authenticated users only.
    Tier rules enforced by URLSerializer.validate().
    """

    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = URLSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        url = serializer.save(owner=request.user)
        return Response(URLSerializer(url).data, status=status.HTTP_201_CREATED)


class URLListView(generics.ListAPIView):
    """
    GET /api/v1/urls/
    Returns only the authenticated user's URLs.
    """

    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return URL.objects.active_urls().filter(owner=self.request.user)


class URLDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/v1/urls/<short_code>/  — public read
    PATCH  /api/v1/urls/<short_code>/  — owner only
    DELETE /api/v1/urls/<short_code>/  — owner only
    """

    queryset = URL.objects.all()
    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    lookup_field = 'short_code'

    def perform_update(self, serializer):
        serializer.save()
        cache.delete(f"url:{serializer.instance.short_code}")

    def perform_destroy(self, instance):
        cache.delete(f"url:{instance.short_code}")
        instance.delete()


class URLAnalyticsView(generics.RetrieveAPIView):
    """
    GET /api/v1/analytics/<short_code>/
    Premium-only. Owner must be the requester.
    Uses DB-level aggregation (no Python loops).
    """

    queryset = URL.objects.all()
    serializer_class = URLAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, IsPremiumUser, IsOwnerOnly]
    lookup_field = 'short_code'


# ---------------------------------------------------------------------------
# Public redirect
# ---------------------------------------------------------------------------

def redirect_view(request, short_code):
    """
    GET /<short_code>/
    Public endpoint — no auth required.
    Cache-first lookup; logs a Click record on hit.
    """

    cache_key = f"url:{short_code}"
    url = cache.get(cache_key)

    if url is None:
        url = get_object_or_404(URL, short_code=short_code, is_active=True)
        cache.set(cache_key, url, CACHE_TTL)

    try:
        with transaction.atomic():
            Click.objects.create(
                url=url,
                ip_address=_get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                referrer=request.META.get('HTTP_REFERER') or None,
            )
            URL.objects.filter(pk=url.pk).update(click_count=url.click_count + 1)
    except Exception:
        pass  # Never let analytics block a redirect

    return redirect(url.original_url)


def _get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
