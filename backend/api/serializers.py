"""
Serializers for the URL Shortener API.

Validation rules enforced here:
  - Registration: email required, password written-only, strong validation
  - URL creation: quota check for Free users, alias gate for non-Premium
  - Social auth: accepts provider + token, returns JWT pair
"""

from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from shortener.models import URL, Click
from shortener.utils import generate_short_code
from core.models import User, TIER_FREE, TIER_PREMIUM, TIER_ADMIN, FREE_TIER_URL_LIMIT


class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Handles new user registration.
    - Password is write-only and validated against Django's password validators.
    - Email is required and must be unique.
    """

    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'password']
        read_only_fields = ['id']

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as e:
            raise serializers.ValidationError(list(e.messages))
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
        )


class UserProfileSerializer(serializers.ModelSerializer):
    """Read-only profile returned after login / registration."""

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'tier', 'is_premium', 'date_joined']
        read_only_fields = fields


class URLSerializer(serializers.ModelSerializer):
    """
    Handles URL creation and updates.

    Business rules enforced:
      1. Free users: max FREE_TIER_URL_LIMIT active URLs.
      2. Free users: cannot set a custom_alias.
      3. custom_alias uniqueness is handled by the model (unique=True).
    """

    owner_username = serializers.CharField(source='owner.username', read_only=True)

    class Meta:
        model = URL
        fields = [
            'id', 'original_url', 'short_code', 'custom_alias',
            'title', 'description', 'favicon',
            'is_active', 'expires_at', 'click_count',
            'tags', 'owner_username', 'created_at',
        ]
        read_only_fields = ['id', 'short_code', 'click_count', 'owner_username', 'created_at']

    def validate(self, data):
        request = self.context.get('request')
        user = getattr(request, 'user', None)

        if not user or not user.is_authenticated:
            return data

        custom_alias = data.get('custom_alias', '').strip() if data.get('custom_alias') else ''

        # --- Alias gate ---
        if custom_alias and user.tier not in (TIER_PREMIUM, TIER_ADMIN):
            raise serializers.ValidationError(
                {"custom_alias": "Custom aliases are a Premium feature. Please upgrade your account."}
            )

        # --- Quota check (only on creation, not updates) ---
        if self.instance is None:  # creation
            if user.tier == TIER_FREE:
                active_count = URL.objects.filter(owner=user, is_active=True).count()
                if active_count >= FREE_TIER_URL_LIMIT:
                    raise serializers.ValidationError(
                        f"Free tier allows a maximum of {FREE_TIER_URL_LIMIT} active URLs. "
                        f"Please upgrade to Premium for unlimited links."
                    )

        return data

    def create(self, validated_data):
        custom_alias = (validated_data.get('custom_alias') or '').strip()
        if custom_alias:
            validated_data['short_code'] = custom_alias
        else:
            for _ in range(10):
                code = generate_short_code()
                if not URL.objects.filter(short_code=code).exists():
                    validated_data['short_code'] = code
                    break
        return super().create(validated_data)


class URLAnalyticsSerializer(serializers.ModelSerializer):
    """
    Premium-only analytics view.
    Aggregates click stats directly in the database — no Python looping.
    """

    clicks_by_country = serializers.SerializerMethodField()
    tags = serializers.StringRelatedField(many=True)

    class Meta:
        model = URL
        fields = [
            'short_code', 'original_url', 'click_count',
            'clicks_by_country', 'tags', 'created_at',
        ]

    def get_clicks_by_country(self, obj):
        return list(Click.objects.clicks_per_country(obj.pk))


class SocialAuthSerializer(serializers.Serializer):
    """
    Accepts a Google ID token and returns a JWT access + refresh pair.
    The view verifies the token with Google; this serializer only
    validates that the required fields are present.
    """

    provider = serializers.ChoiceField(choices=['google'])
    token = serializers.CharField(min_length=10)
