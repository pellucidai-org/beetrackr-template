"""Auth package — fastapi-users wiring (cookie + bearer JWT)."""

from __future__ import annotations

from beets.api.auth.models import User
from beets.api.auth.router import build_auth_router
from beets.api.auth.schemas import UserCreate, UserRead, UserUpdate
from beets.api.auth.users import (
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
