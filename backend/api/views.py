from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404, redirect
from django.http import Http404
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
import logging

from api.serializers import URLSerializer, UserRegistrationSerializer, URLAnalyticsSerializer
from shortener.models import URL
from shortener.tasks import track_click_task, fetch_url_preview_task
from api.permissions import IsOwnerOrReadOnly, IsPremiumUser
from rest_framework_simplejwt.views import TokenObtainPairView

logger = logging.getLogger(__name__)

class UserRegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

class URLCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = URLSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Automatically assign the owner to the current user
            instance = serializer.save(owner=request.user)
            # Trigger metadata fetch asynchronously
            fetch_url_preview_task.delay(instance.id)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class URLListView(generics.ListAPIView):
    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Only list URLs owned by the current user
        return URL.objects.filter(owner=self.request.user)

class URLDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = URL.objects.all()
    serializer_class = URLSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    lookup_field = 'short_code'

    def perform_update(self, serializer):
        instance = serializer.save()
        # Invalidate cache on update
        cache.delete(f"url:{instance.short_code}")

    def perform_destroy(self, instance):
        # Invalidate cache on destroy
        cache.delete(f"url:{instance.short_code}")
        instance.delete()

def redirect_view(request, short_code):
    # Public endpoint, no auth required
    cache_key = f"url:{short_code}"
    cached_data = cache.get(cache_key)
    
    if cached_data:
        if cached_data.get('status') != 'active':
            raise Http404("URL not found or inactive")
        original_url = cached_data['original_url']
        url_id = cached_data['id']
    else:
        try:
            url = URL.objects.get(short_code=short_code)
            if not url.is_active or (url.expires_at and url.expires_at <= timezone.now()):
                # Handle inactive/expired URLs in cache with shorter TTL
                cache.set(cache_key, {'status': 'expired'}, timeout=3600)
                raise Http404("URL not found or inactive")
            
            original_url = url.original_url
            url_id = url.id
            # Cache active URLs for 24 hours
            cache.set(cache_key, {
                'status': 'active', 
                'original_url': original_url, 
                'id': url_id
            }, timeout=86400)
        except URL.DoesNotExist:
            raise Http404("URL not found")
            
    # Extract client data for analytics
    ip_address = request.META.get('HTTP_X_FORWARDED_FOR')
    if ip_address:
        ip_address = ip_address.split(',')[0]
    else:
        ip_address = request.META.get('REMOTE_ADDR')
        
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    referrer = request.META.get('HTTP_REFERER', '')
    
    # Log information in JSON format natively
    request_id = request.headers.get('X-Request-ID', 'unknown')
    logger.info("Redirecting short URL", extra={
        'request_id': request_id,
        'short_code': short_code,
        'user_info': str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else 'anonymous',
        'ip_address': ip_address
    })

    # Dispatch Celery task for asynchronous tracking
    track_click_task.delay(url_id, ip_address, user_agent, None, None, referrer)
    
    return redirect(original_url)

class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        status_data = {'status': 'ok', 'db': 'ok', 'redis': 'ok'}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
        except Exception as e:
            logger.error("DB Health Check Failed", extra={'error': str(e)})
            status_data['db'] = 'error'
            status_data['status'] = 'error'
            
        try:
            cache.set('health_check', '1', timeout=1)
            if cache.get('health_check') != '1':
                raise Exception("Redis set/get failed")
        except Exception as e:
            logger.error("Redis Health Check Failed", extra={'error': str(e)})
            status_data['redis'] = 'error'
            status_data['status'] = 'error'
            
        response_status = status.HTTP_200_OK if status_data['status'] == 'ok' else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(status_data, status=response_status)

class URLAnalyticsView(generics.RetrieveAPIView):
    queryset = URL.objects.all()
    serializer_class = URLAnalyticsSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly, IsPremiumUser]
    lookup_field = 'short_code'

class ThrottledTokenObtainPairView(TokenObtainPairView):
    """
    Subclassing the default JWT Login view to apply custom throttling.
    Scope 'login' is defined in settings.py as 5/minute.
    """
    throttle_scope = 'login'
