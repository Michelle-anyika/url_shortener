"""
Modular permission classes for the URL Shortener API.

Hierarchy:
  IsOwnerOrReadOnly  — safe methods open to all; writes restricted to owner
  IsOwnerOnly        — all methods restricted to the resource owner
  IsPremiumUser      — view accessible only by Premium or Admin tier users
  CanUseCustomAlias  — request-level check for the custom_alias field
"""

from rest_framework import permissions
from core.models import TIER_PREMIUM, TIER_ADMIN


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission.
    - GET / HEAD / OPTIONS  → allowed for everyone (including anonymous)
    - POST / PUT / PATCH / DELETE → allowed only for the resource owner
    """

    message = "You do not have permission to modify another user's resource."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.owner == request.user


class IsOwnerOnly(permissions.BasePermission):
    """
    Object-level permission — only the owner may access this resource
    regardless of HTTP method (no public read).
    """

    message = "You can only access your own resources."

    def has_object_permission(self, request, view, obj):
        return obj.owner == request.user


class IsPremiumUser(permissions.BasePermission):
    """
    View-level permission — grants access only to Premium and Admin tier users.
    Used on analytics and any feature behind the premium gate.
    """

    message = "This feature requires a Premium or Admin account."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.tier in (TIER_PREMIUM, TIER_ADMIN)
        )


class CanUseCustomAlias(permissions.BasePermission):
    """
    Request-level permission — blocks free-tier users from sending a
    custom_alias field. Evaluated before the serializer runs so the
    error message is a 403, not a 400.
    """

    message = "Custom aliases are a Premium feature. Please upgrade your account."

    def has_permission(self, request, view):
        if request.method not in ('POST', 'PUT', 'PATCH'):
            return True
        custom_alias = request.data.get('custom_alias', '').strip()
        if not custom_alias:
            return True  # No alias requested — allow
        return (
            request.user
            and request.user.is_authenticated
            and request.user.tier in (TIER_PREMIUM, TIER_ADMIN)
        )
