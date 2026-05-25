from django.contrib import admin
from shortener.models import URL, Click, Tag


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(URL)
class URLAdmin(admin.ModelAdmin):
    list_display = ('short_code', 'original_url', 'owner', 'is_active', 'click_count', 'expires_at', 'created_at')
    list_filter = ('is_active', 'tags')
    search_fields = ('short_code', 'original_url', 'owner__username', 'owner__email')
    readonly_fields = ('short_code', 'click_count', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    raw_id_fields = ('owner',)


@admin.register(Click)
class ClickAdmin(admin.ModelAdmin):
    list_display = ('url', 'clicked_at', 'ip_address', 'country', 'city')
    list_filter = ('country',)
    search_fields = ('url__short_code', 'ip_address', 'country')
    readonly_fields = ('url', 'clicked_at', 'ip_address', 'city', 'country', 'user_agent', 'referrer')
