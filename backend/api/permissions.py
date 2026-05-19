from rest_framework import permissions
from core.models import tier_premium

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    Assumes the model instance has an `owner` attribute.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so we'll always allow GET, HEAD or OPTIONS requests.
        if request.method in permissions.SAFE_METHODS:
            return True

        # Instance must have an attribute named `owner`.
        return obj.owner == request.user

class IsPremiumUser(permissions.BasePermission):
    """
    Allows access only to premium users.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.tier == tier_premium)
