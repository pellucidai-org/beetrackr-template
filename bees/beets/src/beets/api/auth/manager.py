"""``UserManager`` — fastapi-users hook surface (register/reset/verify).

We log on register / forgot-password / verify so operators get an audit trail
without an extra dependency. Token secrets are read from
:attr:`beets.settings.ApiConfig.jwt_secret` so a single env var
controls every signed token in the app.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi_users import BaseUserManager, UUIDIDMixin
from fastapi_users.db import SQLAlchemyUserDatabase

from beets.api.auth.db import get_user_db
from beets.api.auth.models import User
from beets.logging import get_logger
from beets.settings import get_settings

log = get_logger("auth")


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """fastapi-users manager — handles registration, password, verification."""

    @property
    def reset_password_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().api.jwt_secret

    @property
    def verification_token_secret(self) -> str:  # type: ignore[override]
        return get_settings().api.jwt_secret

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        log.info("auth.user_registered", user_id=str(user.id), email=user.email)

    async def on_after_forgot_password(
        self,
        user: User,
        token: str,
        request: Request | None = None,
    ) -> None:
        log.info(
            "auth.forgot_password_requested",
            user_id=str(user.id),
            email=user.email,
        )

    async def on_after_request_verify(
        self,
        user: User,
        token: str,
        request: Request | None = None,
    ) -> None:
        log.info("auth.verification_requested", user_id=str(user.id), email=user.email)


async def get_user_manager(
    user_db: SQLAlchemyUserDatabase = Depends(get_user_db),
) -> AsyncIterator[UserManager]:
    yield UserManager(user_db)
