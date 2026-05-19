from django.contrib.auth.models import AbstractUser
from django.db import models

tier_free= 'Free'
tier_premium = 'Premium'
tier_admin = 'Admin'
class User(AbstractUser):

    TIER_CHOICES = (
        (tier_free, tier_free),
        (tier_premium, tier_premium),
        (tier_admin, tier_admin),
    )
    email = models.EmailField(unique=True, blank=False, null=False)
    is_premium = models.BooleanField(default=False)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default=tier_free)

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['-date_joined']
