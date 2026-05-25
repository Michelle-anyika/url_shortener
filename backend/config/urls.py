from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from api.views import redirect_view, HealthCheckView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include('api.urls')),

    # API schema & docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/',   SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # Health check — used by load balancers and monitoring
    path('health/', HealthCheckView.as_view(), name='health-check'),

    # Public redirect — must be last
    path('<str:short_code>/', redirect_view, name='redirect-view'),
]
