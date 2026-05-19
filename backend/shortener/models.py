from django.db import models
from django.conf import settings
from django.utils import timezone

class Tag(models.Model):
    name = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name

class URLManager(models.Manager):
    def get_queryset(self):
        # Default queryset does not have select_related to keep it light,
        # but we provide optimized methods below.
        return super().get_queryset()

    def optimized(self):
        """Fetch URLs with their Owners and Tags to prevent N+1."""
        return self.select_related('owner').prefetch_related('tags')

    def active_urls(self):
        now = timezone.now()
        return self.optimized().filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

    def expired_urls(self):
        now = timezone.now()
        return self.optimized().filter(expires_at__lte=now)

    def popular_urls(self):
        return self.optimized().order_by('-click_count')

    def with_click_stats(self):
        """Aggregate clicks per URL grouped by country."""
        from django.db.models import Count
        return self.optimized().annotate(
            total_clicks_recorded=Count('click')
        )

class URL(models.Model):
    original_url = models.URLField()
    short_code = models.CharField(max_length=10, unique=True, db_index=True)
    custom_alias = models.CharField(max_length=50, null=True, blank=True, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.CharField(max_length=500, null=True, blank=True)
    favicon = models.CharField(max_length=255, null=True, blank=True)
    click_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    tags = models.ManyToManyField(Tag, blank=True)
    
    objects = URLManager()

    def __str__(self):
        return f"{self.short_code} -> {self.original_url}"

class ClickManager(models.Manager):
    def clicks_per_country(self, url_id):
        from django.db.models import Count
        return self.filter(url_id=url_id).values('country').annotate(
            total=Count('id')
        ).order_by('-total')

class Click(models.Model):
    url = models.ForeignKey(URL, on_delete=models.CASCADE)
    clicked_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    referrer = models.URLField(null=True, blank=True)

    objects = ClickManager()

    def __str__(self):
        return f"Click on {self.url.short_code} at {self.clicked_at}"
