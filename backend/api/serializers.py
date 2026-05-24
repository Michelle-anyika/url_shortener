from rest_framework import serializers
from shortener.models import URL

class URLSerializer(serializers.ModelSerializer):
    class Meta:
        model = URL
        fields = ['original_url', 'short_code']
        read_only_fields = ['short_code']

    def validate_original_url(self, value):
        """
        Validate that the URL starts with a valid scheme (http:// or https://)
        to prevent generic/malformed strings or malicious JavaScript schemes.
        """
        if not value.startswith(('http://', 'https://')):
            raise serializers.ValidationError("URL must start with http:// or https://")
        return value
