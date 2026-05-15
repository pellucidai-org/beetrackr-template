"""Pydantic schemas exposed by the user / auth endpoints."""

from __future__ import annotations

import uuid

from fastapi_users import schemas


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Response model for ``GET /users/me`` and admin user routes."""


class UserCreate(schemas.BaseUserCreate):
    """Body for ``POST /auth/register``."""


class UserUpdate(schemas.BaseUserUpdate):
    """Body for ``PATCH /users/me`` and admin updates."""
