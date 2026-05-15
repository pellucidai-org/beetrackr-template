"""Database adapter wiring fastapi-users to the shared async session."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from airalo.api.auth.models import User
from airalo.api.database import get_async_session


async def get_user_db(
    session: AsyncSession = Depends(get_async_session),
) -> AsyncIterator[SQLAlchemyUserDatabase]:
    """FastAPI dependency yielding a fastapi-users SQLAlchemy adapter."""
    yield SQLAlchemyUserDatabase(session, User)
