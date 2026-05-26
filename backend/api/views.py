"""
API views — Module 9: Microservices Essentials.

Architecture: All views follow the CQRS pattern.
  - Write operations (POST/PUT/PATCH/DELETE) → Command handlers
  - Read operations (GET) → Query handlers
  - URL creation → URLCreationSaga (coordinates local + remote steps)
"""

import logging
import requests as http_requests

from django.shortcuts import redirect
from django.http import Http404
from django.db import connection
from django.core.cache import cache
from django.utils import timezone

from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, inline_serializer
from drf_spectacular.types import OpenApiTypes
from rest_framework import fields as drf_fields

from api.serializers import (
    UserRegistrationSerializer, UserProfileSerializer,
    URLSerializer, URLAnalyticsSerializer, SocialAuthSerializer,
)
from api.permissions import IsOwnerOrReadOnly, IsOwnerOnly, IsPremiumUser
from shortener.commands import (
    CreateURLCommand, UpdateURLCommand, DeleteURLCommand,
    handle_update_url, handle_delete_url, CommandError,
)
from shortener.queries import (
    get_url_by_code, list_user_urls, get_url_analytics,
    get_clicks_by_country, QueryError,
)
from shortener.saga import URLCreationSaga
from shortener.tasks import track_click_task
from shortener.circuit_breaker import CircuitBreaker
from core.models import User

logger = logging.getLogger(__name__)
CACHE_TTL = 60 * 15


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class URLPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ---------------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------------

class UserRegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response({
            'user': UserProfileSerializer(user).data,
        }, status=status.HTTP_201_CREATED)


class ThrottledTokenObtainPairView(TokenObtainPairView):
    throttle_scope = 'login'


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request=inline_serializer('LogoutRequest', fields={'refresh': drf_fields.CharField()}),
        responses={200: OpenApiResponse(description='Successfully logged out.'),
                   400: OpenApiResponse(description='Missing or invalid refresh token.')},
        summary='Logout',
        description='Blacklists the provided refresh token, invalidating the session.',
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'error': 'refresh token is required'}, status=400)
        try:
            RefreshToken(refresh_token).blacklist()
            return Response({'detail': 'Successfully logged out.'})
        except TokenError as e:
            return Response({'error': str(e)}, status=400)


class SocialAuthView(APIView):
    permission_classes = [permissions.AllowAny]
    GOOGLE_TOKENINFO_URL = 'https://oauth2.googleapis.com/tokeninfo'

    @extend_schema(
        request=SocialAuthSerializer,
        responses={200: UserProfileSerializer,
                   401: OpenApiResponse(description='Invalid or unverifiable token.'),
                   400: OpenApiResponse(description='Unsupported provider.')},
        summary='Social Login (Google)',
        description='Verify a Google ID token and return a JWT access + refresh pair. '
                    'Send provider="google" and the ID token obtained from Google OAuth.',
    )
    def post(self, request):
        serializer = SocialAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        provider = serializer.validated_data['provider']
        token = serializer.validated_data['token']
        if provider != 'google':
            return Response({'error': f"Provider '{provider}' not supported."}, status=400)
        user = self._authenticate_google(token)
        if not user:
            return Response({'error': 'Could not verify social token.'}, status=401)
        refresh = RefreshToken.for_user(user)
        return Response({'user': UserProfileSerializer(user).data,
                         'access': str(refresh.access_token), 'refresh': str(refresh)})

    def _authenticate_google(self, id_token):
        try:
            resp = http_requests.get(self.GOOGLE_TOKENINFO_URL,
                                     params={'id_token': id_token}, timeout=5)
            if resp.status_code != 200:
                return None
            payload = resp.json()
            email = payload.get('email')
            if not email or not payload.get('email_verified', False):
                return None
            user, _ = User.objects.get_or_create(
                email=email, defaults={'username': email.split('@')[0], 'is_active': True})
            return user
        except Exception:
            return None


# ---------------------------------------------------------------------------
# URL views — CQRS
# ---------------------------------------------------------------------------

class URLCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=URLSerializer, responses=URLSerializer)
    def post(self, request):
        serializer = URLSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        cmd = CreateURLCommand(
            original_url=data['original_url'],
            owner=request.user,
            custom_alias=data.get('custom_alias') or None,
            expires_at=data.get('expires_at'),
        )

        try:
            saga = URLCreationSaga()
            result = saga.execute(cmd)
        except CommandError as e:
            return Response({'error': e.message}, status=status.HTTP_400_BAD_REQUEST)

        response_data = URLSerializer(result.url).data
        response_data['preview_queued'] = result.preview_fetched
        logger.info('URL created via saga', extra={
            'short_code': result.url.short_code,
            'preview_queued': result.preview_fetched,
        })
        return Response(response_data, status=status.HTTP_201_CREATED)


class URLListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        responses=URLSerializer(many=True),
        parameters=[
            OpenApiParameter('tag', OpenApiTypes.STR, description='Filter by tag name'),
            OpenApiParameter('search', OpenApiTypes.STR, description='Search by title or URL'),
        ],
    )
    def get(self, request):
        tag = request.query_params.get('tag')
        search = request.query_params.get('search')
        qs = list_user_urls(owner=request.user, tag=tag, search=search)

        paginator = URLPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = URLSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class URLDetailView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]

    @extend_schema(responses=URLSerializer)
    def get(self, request, short_code):
        try:
            url = get_url_by_code(short_code)
        except QueryError:
            return Response({'error': 'Not found'}, status=404)
        return Response(URLSerializer(url).data)

    @extend_schema(request=URLSerializer, responses=URLSerializer)
    def patch(self, request, short_code):
        return self._update(request, short_code)

    @extend_schema(request=URLSerializer, responses=URLSerializer)
    def put(self, request, short_code):
        return self._update(request, short_code)

    def _update(self, request, short_code):
        cmd = UpdateURLCommand(
            short_code=short_code,
            requester=request.user,
            original_url=request.data.get('original_url'),
            expires_at=request.data.get('expires_at'),
        )
        try:
            url = handle_update_url(cmd)
        except CommandError as e:
            code = status.HTTP_404_NOT_FOUND if e.code == 'not_found' else status.HTTP_400_BAD_REQUEST
            return Response({'error': e.message}, status=code)
        return Response(URLSerializer(url).data)

    @extend_schema(
        responses={204: OpenApiResponse(description='URL deleted successfully.'),
                   404: OpenApiResponse(description='URL not found or not owned by you.')},
        summary='Delete URL',
    )
    def delete(self, request, short_code):
        cmd = DeleteURLCommand(short_code=short_code, requester=request.user)
        try:
            handle_delete_url(cmd)
        except CommandError as e:
            return Response({'error': e.message}, status=404)
        return Response(status=status.HTTP_204_NO_CONTENT)


class URLAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsPremiumUser]

    @extend_schema(
        responses={200: URLAnalyticsSerializer,
                   403: OpenApiResponse(description='Premium account required.'),
                   404: OpenApiResponse(description='URL not found or not owned by you.')},
        summary='URL Analytics (Premium)',
        description='Returns click count and geographic breakdown for a URL. '
                    'Requires a Premium or Admin account and ownership of the URL.',
    )
    def get(self, request, short_code):
        try:
            url = get_url_analytics(short_code=short_code, owner=request.user)
        except QueryError as e:
            return Response({'error': e.message}, status=404)

        data = URLAnalyticsSerializer(url).data
        data['clicks_by_country'] = get_clicks_by_country(url)
        return Response(data)


# ---------------------------------------------------------------------------
# Public redirect — write-behind (Module 8) + CQRS query
# ---------------------------------------------------------------------------

def redirect_view(request, short_code):
    cache_key = f'url:{short_code}'
    cached = cache.get(cache_key)

    if cached is not None:
        if cached.get('status') == 'expired':
            raise Http404('URL not found or inactive')
        original_url = cached['original_url']
        url_id = cached['id']
    else:
        try:
            url = get_url_by_code(short_code)
        except QueryError:
            raise Http404('URL not found')

        original_url = url.original_url
        url_id = url.id
        cache.set(cache_key, {
            'status': 'active', 'original_url': original_url, 'id': url_id,
        }, timeout=CACHE_TTL)

    try:
        track_click_task.delay(
            url_id=url_id,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            referrer=request.META.get('HTTP_REFERER') or None,
        )
    except Exception:
        pass  # Never block a redirect

    return redirect(original_url)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        responses={200: OpenApiResponse(description='All systems healthy.'),
                   503: OpenApiResponse(description='One or more services are down.')},
        summary='Health Check',
        description='Probes the database, Redis cache, and preview service circuit breaker. '
                    'Returns 200 if all healthy, 503 if any are degraded.',
    )
    def get(self, request):
        result = {'status': 'ok', 'db': 'ok', 'redis': 'ok', 'preview_circuit': 'ok'}

        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
        except Exception as exc:
            logger.error('Health: DB unreachable', extra={'error': str(exc)})
            result['db'] = 'error'
            result['status'] = 'error'

        try:
            cache.set('_health_probe', '1', timeout=5)
            if cache.get('_health_probe') != '1':
                raise RuntimeError('Cache mismatch')
        except Exception as exc:
            logger.error('Health: Redis unreachable', extra={'error': str(exc)})
            result['redis'] = 'error'
            result['status'] = 'error'

        cb = CircuitBreaker('preview_service')
        cb_status = cb.get_status()
        if cb_status['state'] == 'open':
            result['preview_circuit'] = 'open'

        http_status = 200 if result['status'] == 'ok' else 503
        return Response(result, status=http_status)


def _get_client_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    return forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')
