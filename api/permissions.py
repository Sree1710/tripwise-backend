# api/permissions.py
from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        payload = request.auth  # we passed payload as "auth" in authenticate()
        return payload and payload.get("role") == "admin"


class IsUser(BasePermission):
    def has_permission(self, request, view):
        payload = request.auth
        return payload and payload.get("role") == "user"


class IsAdminOrUser(BasePermission):
    def has_permission(self, request, view):
        payload = request.auth
        return payload and payload.get("role") in ["admin", "user"]
