from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404, redirect
from api.serializers import URLSerializer, UserRegistrationSerializer, URLAnalyticsSerializer
from shortener.models import URL
from api.permissions import IsOwnerOrReadOnly, IsPremiumUser
from rest_framework_simplejwt.views import TokenObtainPairView

class UserRegisterView(generics.CreateAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

class URLCreateView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = URLSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            # Automatically assign the owner to the current user
            serializer.save(owner=request.user)
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

def redirect_view(request, short_code):
    # Public endpoint, no auth required
    url = get_object_or_404(URL, short_code=short_code, is_active=True)
    # TODO: Track click analytics here (Module 8 focus)
    return redirect(url.original_url)

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
