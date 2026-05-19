import pytest
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from core.models import User

@pytest.mark.django_db
class TestUserModel:
    def test_create_user_with_valid_data(self):
        user = User.objects.create_user(
            username='testuser', 
            email='test@example.com', 
            password='password123'
        )
        assert user.username == 'testuser'
        assert user.email == 'test@example.com'
        assert user.is_premium is False
        assert user.tier == 'Free'

    def test_create_user_premium_tier(self):
        user = User.objects.create_user(
            username='premiumuser', 
            email='premium@example.com', 
            password='password123',
            is_premium=True,
            tier='Premium'
        )
        assert user.is_premium is True
        assert user.tier == 'Premium'

    def test_email_is_unique(self):
        User.objects.create_user(username='user1', email='shared@example.com', password='password123')
        
        with pytest.raises(IntegrityError):
            User.objects.create_user(username='user2', email='shared@example.com', password='password123')

    def test_email_is_required_for_full_clean(self):
        user = User(username='noemail')
        # Django's AbstractUser allows blank emails by default, but we will enforce it.
        # So full_clean() should raise ValidationError
        with pytest.raises(ValidationError) as exc_info:
            user.full_clean()
        
        assert 'email' in exc_info.value.message_dict

    def test_tier_choices(self):
        user = User(username='invalidtier', email='test@example.com', tier='Invalid')
        with pytest.raises(ValidationError) as exc_info:
            user.full_clean()
            
        assert 'tier' in exc_info.value.message_dict
