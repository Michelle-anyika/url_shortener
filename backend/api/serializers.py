from rest_framework import serializers
from shortener.models import URL
from core.models import User
from shortener.utils import generate_short_code

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password']

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user

class URLSerializer(serializers.ModelSerializer):
    class Meta:
        model = URL
        fields = ['original_url', 'short_code', 'custom_alias', 'title', 'description', 'favicon']
        read_only_fields = ['short_code']

    def validate(self, data):
        request = self.context.get('request')
        user = request.user if request and request.user.is_authenticated else None

        # Custom Alias Check
        custom_alias = data.get('custom_alias')
        if custom_alias:
            if not user or user.tier != 'Premium':
                raise serializers.ValidationError({"custom_alias": "Custom aliases are a Premium feature."})
            
        # Quota Check
        if user and user.tier == 'Free':
            active_count = URL.objects.filter(owner=user, is_active=True).count()
            if active_count >= 10:
                raise serializers.ValidationError("Free tier allows a maximum of 10 active URLs.")
                
        return data

    def create(self, validated_data):
        # Generate a unique short code if custom_alias is not provided or if it's separate
        # Usually, short_code is automatically generated. Custom alias can be used in place of short_code or alongside.
        # We will use custom_alias as the short_code if provided, otherwise generate one.
        custom_alias = validated_data.get('custom_alias')
        
        if custom_alias:
            code = custom_alias
        else:
            while True:
                code = generate_short_code()
                if not URL.objects.filter(short_code=code).exists():
                    break
        
        validated_data['short_code'] = code
        return super().create(validated_data)

class URLAnalyticsSerializer(serializers.ModelSerializer):
    country_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = URL
        fields = ['short_code', 'original_url', 'click_count', 'country_breakdown']

    def get_country_breakdown(self, obj):
        from shortener.models import Click
        return Click.objects.clicks_per_country(obj.id)


