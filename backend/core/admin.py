from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from core.models import User, TIER_FREE, TIER_PREMIUM, TIER_ADMIN


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'tier', 'is_premium', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('tier', 'is_premium', 'is_staff', 'is_active')
    search_fields = ('username', 'email')
    ordering = ('-date_joined',)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('Tier & Access', {'fields': ('tier',)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('Tier & Access', {'fields': ('email', 'tier')}),
    )

    readonly_fields = ('is_premium',)
    actions = ['make_premium', 'make_admin', 'make_free']

    @admin.action(description='Promote selected users to Premium')
    def make_premium(self, request, queryset):
        count = 0
        for user in queryset:
            user.tier = TIER_PREMIUM
            user.save()
            count += 1
        self.message_user(request, f'{count} user(s) promoted to Premium.')

    @admin.action(description='Promote selected users to Admin')
    def make_admin(self, request, queryset):
        count = 0
        for user in queryset:
            user.tier = TIER_ADMIN
            user.is_staff = True
            user.save()
            count += 1
        self.message_user(request, f'{count} user(s) promoted to Admin.')

    @admin.action(description='Downgrade selected users to Free')
    def make_free(self, request, queryset):
        count = 0
        for user in queryset:
            user.tier = TIER_FREE
            user.save()
            count += 1
        self.message_user(request, f'{count} user(s) downgraded to Free.')
