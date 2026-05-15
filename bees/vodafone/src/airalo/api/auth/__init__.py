"""Auth package — fastapi-users wiring (cookie + bearer JWT)."""

from __future__ import annotations

from airalo.api.auth.models import User
from airalo.api.auth.router import build_auth_router
from airalo.api.auth.schemas import UserCreate, UserRead, UserUpdate
from airalo.api.auth.users import (
    current_active_user,
    current_optional_user,
    current_superuser,
    fastapi_users,
)

__all__ = [
    "User",
    "UserCreate",
    "UserRead",
    "UserUpdate",
    "build_auth_router",
    "current_active_user",
    "current_optional_user",
    "current_superuser",
    "fastapi_users",
]
