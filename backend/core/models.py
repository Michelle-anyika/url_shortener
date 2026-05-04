from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    TIER_CHOICES = (
        ('Free', 'Free'),
        ('Premium', 'Premium'),
        ('Admin', 'Admin'),
    )
    email = models.EmailField(unique=True, blank=False, null=False)
    is_premium = models.BooleanField(default=False)
    tier = models.CharField(max_length=20, choices=TIER_CHOICES, default='Free')

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ['-date_joined']
