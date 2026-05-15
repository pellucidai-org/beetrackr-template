"""Shared async SQLAlchemy session for API + auth + fetch routes.

This is intentionally separate from :mod:`beets.storage.sql`: the
storage backend is consumed by scrapers (short-lived, batch writes), whereas
the API needs a long-lived engine/session-maker scoped to the FastAPI app.

Both can target the same database — set ``api.database_url`` to share, or
leave it blank to inherit ``storage.database_url``. Calling :func:`init_db`
at startup runs ``Base.metadata.create_all`` so the ``scraped_items``,
``page_artifacts`` and ``users`` tables exist before the first request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from beets.logging import get_logger
from beets.settings import Settings, get_settings
from beets.storage.models import Base

log = get_logger("api.db")

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _resolve_url(settings: Settings) -> str:
    """Pick the API DB URL, falling back to storage.database_url."""
    return settings.api.database_url or settings.storage.database_url


def get_engine() -> AsyncEngine:
    """Return the (lazily-created) module-level engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        url = _resolve_url(settings)
        engine_kwargs: dict[str, Any] = {
            "echo": settings.storage.sql_echo,
            "future": True,
        }
        if not url.startswith("sqlite"):
            engine_kwargs["pool_size"] = settings.storage.sql_pool_size
        _engine = create_async_engine(url, **engine_kwargs)
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Return the (lazily-created) async sessionmaker bound to the engine."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), expire_on_commit=False, class_=AsyncSession
        )
    return _sessionmaker


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one session per request."""
    session_maker = get_session_maker()
    async with session_maker() as session:
        yield session


async def init_db() -> None:
    """Create all known tables. Called once from the FastAPI lifespan.

    The :class:`User` model is imported here (rather than at module top-level)
    so it registers on ``Base.metadata`` *after* all modules have loaded —
    avoids a circular import between ``api.auth.*`` and ``api.database``.
    """
    from beets.api.auth.models import User  # noqa: F401

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("api.db.create_all", url=_redact(str(engine.url)))


async def close_db() -> None:
    """Dispose the engine + clear module state. Called on app shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def _redact(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
