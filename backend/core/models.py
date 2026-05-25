from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Extended user model adding premium tier support.
    is_premium: quick boolean flag for premium access checks.
    tier: named tier level (free / pro / enterprise).
    """

    TIER_FREE = 'free'
    TIER_PRO = 'pro'
    TIER_ENTERPRISE = 'enterprise'

    TIER_CHOICES = [
        (TIER_FREE, 'Free'),
        (TIER_PRO, 'Pro'),
        (TIER_ENTERPRISE, 'Enterprise'),
    ]

    is_premium = models.BooleanField(default=False)
    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default=TIER_FREE,
    )

    def __str__(self):
        return self.username
