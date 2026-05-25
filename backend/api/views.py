"""
API views — Module 8: Advanced Optimization & Production Readiness.

Key changes from Module 7:
  - redirect_view: Write-Behind pattern — Click is tracked via Celery task,
    not written synchronously in the request. Response time is now O(cache).
  - HealthCheckView: probes DB and Redis; returns 200 or 503.
  - All views use structured JSON logging for 500s and security events.
"""

import logging
import requests as http_requests

from django.shortcuts import get_object_or_404, redirect
from django.http import Http404
from django.db import transaction, connection
from django.core.cache import cache
from django.utils import timezone

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
from shortener.tasks import track_click_task
from core.models import User

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 15  # 15 minutes


# ---------------------------------------------------------------------------
# Auth views (carried from Module 7 — unchanged)
# ---------------------------------------------------------------------------

class UserRegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                'user': UserProfileSerializer(user).data,
                'access': str(refresh.access_token),
                'refresh': str(refresh),
            },
            status=status.HTTP_201_CREATED,
        )


class ThrottledTokenObtainPairView(TokenObtainPairView):
    """Rate-limited login — 5 requests per minute."""
    throttle_scope = 'login'


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'refresh token is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({'detail': 'Successfully logged out.'})
        except TokenError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class SocialAuthView(APIView):
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
            return Response({'error': f"Provider '{provider}' is not supported."}, status=400)
        if user is None:
            return Response({'error': 'Could not verify social token.'}, status=status.HTTP_401_UNAUTHORIZED)
        refresh = RefreshToken.for_user(user)
        return Response({'user': UserProfileSerializer(user).data,
                         'access': str(refresh.access_token), 'refresh': str(refresh)})

    def _authenticate_google(self, id_token):
        try:
            resp = http_requests.get(self.GOOGLE_TOKENINFO_URL, params={'id_token': id_token}, timeout=5)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            email = payload.get('email')
            if not email or not payload.get('email_verified', False):
                return None
            user, _ = User.objects.get_or_create(email=email,
                                                  defaults={'username': email.split('@')[0], 'is_active': True})
            return user
        except Exception:
            return None


# ---------------------------------------------------------------------------
# URL CRUD views
# ---------------------------------------------------------------------------

class URLCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = URLSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        url = serializer.save(owner=request.user)
        logger.info('URL created', extra={'short_code': url.short_code, 'user': request.user.username})
        return Response(URLSerializer(url).data, status=status.HTTP_201_CREATED)


class URLListView(generics.ListAPIView):
    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return URL.objects.active_urls().filter(owner=self.request.user)


class URLDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = URL.objects.all()
    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    lookup_field = 'short_code'

    def perform_update(self, serializer):
        instance = serializer.save()
        # Cache invalidation — must evict immediately on any update
        cache.delete(f'url:{instance.short_code}')
        logger.info('URL updated, cache invalidated', extra={'short_code': instance.short_code})

    def perform_destroy(self, instance):
        cache.delete(f'url:{instance.short_code}')
        logger.info('URL deleted, cache invalidated', extra={'short_code': instance.short_code})
        instance.delete()


class URLAnalyticsView(generics.RetrieveAPIView):
    queryset = URL.objects.all()
    serializer_class = URLAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, IsPremiumUser, IsOwnerOnly]
    lookup_field = 'short_code'


# ---------------------------------------------------------------------------
# Public redirect — Write-Behind pattern
# ---------------------------------------------------------------------------

def redirect_view(request, short_code):
    """
    GET /<short_code>/

    Performance path:
      1. Check Redis cache  → hit: redirect immediately (no DB query)
      2. Cache miss         → query DB, populate cache, redirect
      3. Fire Celery task   → track_click_task.delay() records the Click
                              asynchronously (write-behind pattern).

    The user receives the redirect before any DB write happens.
    """
    cache_key = f'url:{short_code}'
    cached = cache.get(cache_key)

    if cached is not None:
        # Fast path — served entirely from Redis
        if cached.get('status') == 'expired':
            raise Http404('URL not found or inactive')
        original_url = cached['original_url']
        url_id = cached['id']
    else:
        # Slow path — DB lookup, then populate cache
        try:
            url = URL.objects.get(short_code=short_code)
        except URL.DoesNotExist:
            raise Http404('URL not found')

        if not url.is_active or (url.expires_at and url.expires_at <= timezone.now()):
            cache.set(cache_key, {'status': 'expired'}, timeout=3600)
            raise Http404('URL not found or inactive')

        original_url = url.original_url
        url_id = url.id
        cache.set(cache_key, {
            'status': 'active',
            'original_url': original_url,
            'id': url_id,
        }, timeout=CACHE_TTL)

    # --- Write-Behind: fire and forget ---
    ip_address = _get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    referrer = request.META.get('HTTP_REFERER') or None

    track_click_task.delay(
        url_id=url_id,
        ip_address=ip_address,
        user_agent=user_agent,
        referrer=referrer,
    )

    logger.info(
        'Redirect served',
        extra={
            'short_code': short_code,
            'cache_hit': cached is not None,
            'ip': ip_address,
        },
    )
    return redirect(original_url)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthCheckView(APIView):
    """
    GET /health/

    Probes the two critical external dependencies:
      - Database: runs a lightweight SELECT 1
      - Redis (cache): sets and reads a test key

    Returns 200 if both are healthy, 503 if either is down.
    Used by load balancers and monitoring tools (Prometheus, uptime checks).
    """

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        result = {
            'status': 'ok',
            'db': 'ok',
            'redis': 'ok',
        }

        # --- Database probe ---
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception as exc:
            logger.error('Health check: DB unreachable', extra={'error': str(exc)})
            result['db'] = 'error'
            result['status'] = 'error'

        # --- Redis probe ---
        try:
            cache.set('_health_probe', '1', timeout=5)
            if cache.get('_health_probe') != '1':
                raise RuntimeError('Cache set/get mismatch')
        except Exception as exc:
            logger.error('Health check: Redis unreachable', extra={'error': str(exc)})
            result['redis'] = 'error'
            result['status'] = 'error'

        http_status = status.HTTP_200_OK if result['status'] == 'ok' else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(result, status=http_status)


def _get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')
