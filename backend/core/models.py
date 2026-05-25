from django.contrib.auth.models import AbstractUser
from django.db import models

# Tier constants — used across the project for tier comparisons
TIER_FREE = 'Free'
TIER_PREMIUM = 'Premium'
TIER_ADMIN = 'Admin'

TIER_CHOICES = [
    (TIER_FREE, 'Free'),
    (TIER_PREMIUM, 'Premium'),
    (TIER_ADMIN, 'Admin'),
]

# Business rules
FREE_TIER_URL_LIMIT = 10  # max active URLs for a free user


class User(AbstractUser):
    """
    Extended user model.

    Tiers:
      Free      — max 10 active URLs, no custom aliases, no analytics
      Premium   — unlimited URLs, custom aliases, full analytics access
      Admin     — staff access, all Premium features
    """

    email = models.EmailField(unique=True, blank=False, null=False)
    is_premium = models.BooleanField(default=False)
    tier = models.CharField(
        max_length=20,
        choices=TIER_CHOICES,
        default=TIER_FREE,
    )

    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.username} ({self.tier})"

    @property
    def is_premium_or_admin(self):
        return self.tier in (TIER_PREMIUM, TIER_ADMIN)

    def save(self, *args, **kwargs):
        # Keep is_premium in sync with tier automatically
        self.is_premium = self.tier in (TIER_PREMIUM, TIER_ADMIN)
        super().save(*args, **kwargs)
