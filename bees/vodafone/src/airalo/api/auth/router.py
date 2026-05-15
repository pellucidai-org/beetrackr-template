"""Assemble the auth + users routers respecting :class:`ApiConfig` toggles."""

from __future__ import annotations

from fastapi import APIRouter

from airalo.api.auth.backend import bearer_backend, cookie_backend
from airalo.api.auth.schemas import UserCreate, UserRead, UserUpdate
from airalo.api.auth.users import fastapi_users
from airalo.settings import get_settings


def build_auth_router() -> APIRouter:
    """Return a combined APIRouter mounting cookie + bearer + users routes."""
    settings = get_settings()
    router = APIRouter()

    router.include_router(
        fastapi_users.get_auth_router(cookie_backend),
        prefix="/auth/cookie",
        tags=["auth"],
    )
    router.include_router(
        fastapi_users.get_auth_router(bearer_backend),
        prefix="/auth/bearer",
        tags=["auth"],
    )

    if settings.api.allow_registration:
        router.include_router(
            fastapi_users.get_register_router(UserRead, UserCreate),
            prefix="/auth",
            tags=["auth"],
        )

    router.include_router(
        fastapi_users.get_reset_password_router(),
        prefix="/auth",
        tags=["auth"],
    )

    if settings.api.verify_users:
        router.include_router(
            fastapi_users.get_verify_router(UserRead),
            prefix="/auth",
            tags=["auth"],
        )

    router.include_router(
        fastapi_users.get_users_router(UserRead, UserUpdate),
        prefix="/users",
        tags=["users"],
    )

    return router
