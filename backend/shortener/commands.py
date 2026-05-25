"""
CQRS — Command Side.

Commands represent intentions to change state.
Each command is a plain dataclass; each handler is a function that
executes exactly one state change and returns the result.

Command handlers are the ONLY place that writes to the database.
Views must never call ORM methods directly — they go through commands.

Commands
--------
CreateURLCommand   — create a new short URL
UpdateURLCommand   — update an existing URL's fields
DeleteURLCommand   — permanently delete a URL
DeactivateURLCommand — soft-delete (set is_active=False)
"""

from dataclasses import dataclass, field
from typing import Optional, List
from django.db import transaction
from django.core.cache import cache

from shortener.models import URL, Tag
from shortener.utils import generate_short_code
from core.models import User, TIER_FREE, TIER_PREMIUM, TIER_ADMIN, FREE_TIER_URL_LIMIT


# ---------------------------------------------------------------------------
# Command dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CreateURLCommand:
    original_url: str
    owner: User
    custom_alias: Optional[str] = None
    expires_at: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    favicon: Optional[str] = None
    tag_names: List[str] = field(default_factory=list)


@dataclass
class UpdateURLCommand:
    short_code: str
    requester: User
    original_url: Optional[str] = None
    expires_at: Optional[str] = None
    is_active: Optional[bool] = None
    title: Optional[str] = None
    description: Optional[str] = None


@dataclass
class DeleteURLCommand:
    short_code: str
    requester: User


@dataclass
class DeactivateURLCommand:
    short_code: str
    requester: User


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

class CommandError(Exception):
    """Raised when a command violates a business rule."""
    def __init__(self, message: str, code: str = 'command_error'):
        self.message = message
        self.code = code
        super().__init__(message)


@transaction.atomic
def handle_create_url(cmd: CreateURLCommand) -> URL:
    """
    Validates business rules then creates the URL record.
    Raises CommandError for quota or alias violations.
    """
    # --- Quota check ---
    if cmd.owner.tier == TIER_FREE:
        active_count = URL.objects.filter(owner=cmd.owner, is_active=True).count()
        if active_count >= FREE_TIER_URL_LIMIT:
            raise CommandError(
                f"Free tier allows a maximum of {FREE_TIER_URL_LIMIT} active URLs.",
                code='quota_exceeded',
            )

    # --- Alias gate ---
    if cmd.custom_alias and cmd.owner.tier not in (TIER_PREMIUM, TIER_ADMIN):
        raise CommandError(
            "Custom aliases are a Premium feature.",
            code='permission_denied',
        )

    # --- Generate or validate short code ---
    if cmd.custom_alias:
        if URL.objects.filter(short_code=cmd.custom_alias).exists():
            raise CommandError(
                f"The alias '{cmd.custom_alias}' is already taken.",
                code='duplicate_alias',
            )
        short_code = cmd.custom_alias
    else:
        for _ in range(10):
            short_code = generate_short_code()
            if not URL.objects.filter(short_code=short_code).exists():
                break
        else:
            raise CommandError("Could not generate a unique short code.", code='server_error')

    url = URL.objects.create(
        original_url=cmd.original_url,
        short_code=short_code,
        custom_alias=cmd.custom_alias,
        owner=cmd.owner,
        expires_at=cmd.expires_at,
        title=cmd.title,
        description=cmd.description,
        favicon=cmd.favicon,
    )

    if cmd.tag_names:
        tags = Tag.objects.filter(name__in=cmd.tag_names)
        url.tags.set(tags)

    return url


@transaction.atomic
def handle_update_url(cmd: UpdateURLCommand) -> URL:
    try:
        url = URL.objects.select_for_update().get(
            short_code=cmd.short_code, owner=cmd.requester
        )
    except URL.DoesNotExist:
        raise CommandError("URL not found or you do not own it.", code='not_found')

    if cmd.original_url is not None:
        url.original_url = cmd.original_url
    if cmd.expires_at is not None:
        url.expires_at = cmd.expires_at
    if cmd.is_active is not None:
        url.is_active = cmd.is_active
    if cmd.title is not None:
        url.title = cmd.title
    if cmd.description is not None:
        url.description = cmd.description

    url.save()
    cache.delete(f'url:{url.short_code}')
    return url


@transaction.atomic
def handle_delete_url(cmd: DeleteURLCommand) -> None:
    try:
        url = URL.objects.get(short_code=cmd.short_code, owner=cmd.requester)
    except URL.DoesNotExist:
        raise CommandError("URL not found or you do not own it.", code='not_found')
    cache.delete(f'url:{url.short_code}')
    url.delete()


@transaction.atomic
def handle_deactivate_url(cmd: DeactivateURLCommand) -> URL:
    try:
        url = URL.objects.select_for_update().get(
            short_code=cmd.short_code, owner=cmd.requester
        )
    except URL.DoesNotExist:
        raise CommandError("URL not found or you do not own it.", code='not_found')
    url.is_active = False
    url.save(update_fields=['is_active'])
    cache.delete(f'url:{url.short_code}')
    return url
