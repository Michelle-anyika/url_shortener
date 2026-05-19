from rest_framework import serializers
from shortener.models import URL
from shortener.utils import generate_short_code

class URLSerializer(serializers.ModelSerializer):
    class Meta:
        model = URL
        fields = ['original_url', 'short_code']
        read_only_fields = ['short_code']

    def create(self, validated_data):
        # Generate a unique short code
        while True:
            code = generate_short_code()
            if not URL.objects.filter(short_code=code).exists():
                break
        
        validated_data['short_code'] = code
        return super().create(validated_data)
