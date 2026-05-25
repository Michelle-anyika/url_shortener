from django.db import models
from django.conf import settings
from django.utils import timezone
from django.db.models import Count


# ---------------------------------------------------------------------------
# Tag
# ---------------------------------------------------------------------------

class Tag(models.Model):
    """Simple label used to categorise URLs (e.g. Marketing, Social)."""

    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


# ---------------------------------------------------------------------------
# URL – custom manager & queryset
# ---------------------------------------------------------------------------

class URLQuerySet(models.QuerySet):
    """Reusable, chainable queryset for URL."""

    def optimized(self):
        """Fetch URLs together with their owner and tags to prevent N+1."""
        return self.select_related('owner').prefetch_related('tags')

    def active(self):
        now = timezone.now()
        return self.filter(is_active=True).filter(
            models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=now)
        )

    def expired(self):
        now = timezone.now()
        return self.filter(
            models.Q(is_active=False) | models.Q(expires_at__lte=now)
        )

    def popular(self):
        return self.order_by('-click_count')

    def with_click_stats(self):
        """Annotate each URL with its total recorded clicks (DB aggregation)."""
        return self.annotate(total_clicks_recorded=Count('click'))


class URLManager(models.Manager):
    """
    Custom manager exposing semantic query methods.
    All methods return optimized querysets (select_related + prefetch_related)
    so callers never trigger N+1 queries by accident.
    """

    def get_queryset(self):
        return URLQuerySet(self.model, using=self._db)

    def active_urls(self):
        """All non-expired, active URLs."""
        return self.get_queryset().optimized().active()

    def expired_urls(self):
        """URLs that have expired or been deactivated."""
        return self.get_queryset().optimized().expired()

    def popular_urls(self):
        """URLs ordered by click count descending."""
        return self.get_queryset().optimized().popular()

    def with_click_stats(self):
        """URLs annotated with aggregated click counts."""
        return self.get_queryset().optimized().with_click_stats()


class URL(models.Model):
    """
    Core URL model.
    Indexes on short_code (lookups) and created_at (time-range queries).
    """

    original_url = models.URLField()
    short_code = models.CharField(max_length=10, unique=True, db_index=True)
    custom_alias = models.CharField(max_length=50, null=True, blank=True, unique=True)

    # Ownership
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='urls',
    )

    # Status & lifecycle
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    # Analytics counter (denormalised for fast reads)
    click_count = models.PositiveIntegerField(default=0)

    # Rich metadata
    title = models.CharField(max_length=255, null=True, blank=True)
    description = models.CharField(max_length=500, null=True, blank=True)
    favicon = models.CharField(max_length=255, null=True, blank=True)

    # Categorisation
    tags = models.ManyToManyField(Tag, blank=True, related_name='urls')

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = URLManager()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.short_code} -> {self.original_url}"

    @property
    def is_expired(self):
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at


# ---------------------------------------------------------------------------
# Click – custom manager
# ---------------------------------------------------------------------------

class ClickQuerySet(models.QuerySet):

    def for_url(self, url_id):
        return self.filter(url_id=url_id)

    def clicks_per_country(self, url_id):
        """
        Aggregate click counts grouped by country directly in the database.
        Returns a queryset of {'country': ..., 'total': ...} dicts.
        """
        return (
            self.for_url(url_id)
            .values('country')
            .annotate(total=Count('id'))
            .order_by('-total')
        )


class ClickManager(models.Manager):

    def get_queryset(self):
        return ClickQuerySet(self.model, using=self._db)

    def clicks_per_country(self, url_id):
        return self.get_queryset().clicks_per_country(url_id)


class Click(models.Model):
    """Logs every visit to a short URL for analytics."""

    url = models.ForeignKey(URL, on_delete=models.CASCADE, related_name='click_set')
    clicked_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    city = models.CharField(max_length=100, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    referrer = models.URLField(null=True, blank=True)

    objects = ClickManager()

    class Meta:
        ordering = ['-clicked_at']

    def __str__(self):
        return f"Click on {self.url.short_code} at {self.clicked_at}"
