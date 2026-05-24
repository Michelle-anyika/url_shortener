from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import redirect
from api.serializers import URLSerializer
from drf_spectacular.utils import extend_schema, OpenApiResponse

class URLCreateView(APIView):
    # The service dependency is injected (e.g. inside urls.py or tests)
    service = None

    @extend_schema(
        request=URLSerializer,
        responses={
            201: URLSerializer,
            400: OpenApiResponse(description="Invalid request payload or malformed URL scheme")
        },
        summary="Create a Shortened URL",
        description="Accepts a long destination URL and returns a unique 6-character alphanumeric short code."
    )
    def post(self, request):
        if not self.service:
            raise ValueError("URLService dependency is not injected.")

        serializer = URLSerializer(data=request.data)
        if serializer.is_valid():
            original_url = serializer.validated_data['original_url']
            url_obj = self.service.create_short_url(original_url)
            response_serializer = URLSerializer(url_obj)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class URLRedirectView(APIView):
    # The service dependency is injected
    service = None

    @extend_schema(
        responses={
            302: OpenApiResponse(description="Successful redirection to original destination URL"),
            404: OpenApiResponse(description="Short code does not exist in the system")
        },
        summary="Redirect to Destination URL",
        description="Looks up the short code in the registry and redirects the client using an HTTP 302 redirect."
    )
    def get(self, request, short_code):
        if not self.service:
            raise ValueError("URLService dependency is not injected.")

        url_obj = self.service.get_url_by_code(short_code)
        if not url_obj:
            return Response({"detail": "Short URL not found."}, status=status.HTTP_404_NOT_FOUND)
        
        return redirect(url_obj.original_url)
