"""Shared API-key auth for read endpoints.

When ``settings.API_KEY`` is set, requests must send a matching ``X-API-Key``
or ``Authorization: Bearer <key>``. When unset (local/dev), access is open —
set the key on any hosted instance.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission
from rest_framework.request import Request


class AnonymousAPIUser:
    is_authenticated = True
    is_anonymous = False

    def __str__(self) -> str:
        return "api-key"


def _provided_key(request: Request) -> str:
    provided = request.headers.get("X-API-Key")
    if provided:
        return provided
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class APIKeyAuthentication(BaseAuthentication):
    """Authenticate via shared API key; advertise a scheme so failures are 401."""

    def authenticate(self, request: Request) -> tuple[AnonymousAPIUser, None] | None:
        expected = getattr(settings, "API_KEY", "") or ""
        if not expected:
            return (AnonymousAPIUser(), None)

        provided = _provided_key(request)
        if not provided:
            raise AuthenticationFailed("missing API key")
        if provided != expected:
            raise AuthenticationFailed("invalid API key")
        return (AnonymousAPIUser(), None)

    def authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="data-store"'


class HasAPIKey(BasePermission):
    def has_permission(self, request: Request, view: object) -> bool:
        return bool(getattr(request.user, "is_authenticated", False))
