"""SQLAlchemy async backend (SQLite, PostgreSQL, Supabase).

Driver matrix (configured via ``storage.database_url``)::

    sqlite+aiosqlite:///./data/scraper.db                     -> aiosqlite
    postgresql+asyncpg://user:pass@host:5432/db               -> asyncpg
    postgresql+asyncpg://postgres:<pwd>@db.<ref>.supabase.co  -> asyncpg

For Postgres/Supabase make sure ``asyncpg`` is installed (it is, by default,
via this project's ``pyproject.toml``).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from airalo.artifacts.models import PageArtifacts
from airalo.logging import get_logger
from airalo.settings import Settings
from airalo.storage.base import ScrapedItem
from airalo.storage.models import Base, PageArtifactORM, ScrapedItemORM

log = get_logger("storage.sql")


class SQLAlchemyBackend:
    """Async SQLAlchemy backend backed by SQLite/Postgres/Supabase."""

    name = "sql"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: AsyncEngine | None = None
        self._sessionmaker: async_sessionmaker[AsyncSession] | None = None

    # ---- lifecycle --------------------------------------------------------

    async def init(self) -> None:
        if self._engine is not None:
            return

        cfg = self._settings.storage
        url = cfg.database_url

        engine_kwargs: dict[str, Any] = {"echo": cfg.sql_echo, "future": True}
        if not url.startswith("sqlite"):
            # SQLite uses an in-memory or single-file store; pool_size is a no-op.
            engine_kwargs["pool_size"] = cfg.sql_pool_size

        self._engine = await self._create_engine(url, **engine_kwargs)
        self._sessionmaker = async_sessionmaker(
            self._engine, expire_on_commit=False, class_=AsyncSession
        )

        if cfg.sql_create_tables:
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            log.info("sql.create_all", url=_redact(url))

        log.info("sql.connected", url=_redact(url))

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessionmaker = None

    # ---- write path -------------------------------------------------------

    async def save(self, target: str, records: Iterable[dict[str, Any]]) -> int:
        if self._sessionmaker is None:
            await self.init()
        assert self._sessionmaker is not None

        items = [ScrapedItem.from_record(target, r) for r in records]
        if not items:
            return 0

        rows = [
            ScrapedItemORM(
                job_id=item.job_id,
                record_id=item.record_id,
                scraper_key=item.scraper_key,
                target=item.target,
                url=item.url,
                status=item.status,
                data=item.data,
                metadata_=item.metadata,
                scraped_at=item.scraped_at,
            )
            for item in items
        ]

        # Flatten metadata.artifacts.items into the page_artifacts table so
        # the path/kind columns become indexable.
        artifact_rows: list[PageArtifactORM] = []
        for item in items:
            arts_payload = item.metadata.get("artifacts") if item.metadata else None
            arts = PageArtifacts.from_dict(arts_payload)
            for a in arts:
                artifact_rows.append(
                    PageArtifactORM(
                        record_id=item.record_id,
                        job_id=item.job_id,
                        target=item.target,
                        kind=a.kind,
                        path=a.path,
                        media_type=a.media_type,
                        size_bytes=a.size_bytes,
                        width=a.width,
                        height=a.height,
                        duration_ms=a.duration_ms,
                        extra=a.extra or None,
                        created_at=a.created_at,
                    )
                )

        async with self._sessionmaker() as session:
            session.add_all(rows)
            if artifact_rows:
                session.add_all(artifact_rows)
            await session.commit()

        log.info(
            "sql.save",
            target=target,
            count=len(rows),
            artifact_count=len(artifact_rows),
        )
        return len(rows)

    # ---- engine factory with retries -------------------------------------

    async def _create_engine(self, url: str, **kwargs: Any) -> AsyncEngine:
        """Create an engine with Tenacity-driven retries.

        Hardens against transient DNS / handshake failures when talking to
        managed Postgres (Supabase, RDS, ...).
        """
        cfg = self._settings.scraper

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(cfg.max_retries),
            wait=wait_exponential(multiplier=cfg.retry_backoff, min=1, max=15),
            retry=retry_if_exception_type(Exception),
            before_sleep=before_sleep_log(log, log_level=30),  # WARNING
            reraise=True,
        ):
            with attempt:
                engine = create_async_engine(url, **kwargs)
                # Eagerly open & close a connection so misconfiguration fails
                # here (during init) rather than on the first real query.
                async with engine.connect():
                    pass
                return engine

        raise RuntimeError("unreachable")  # pragma: no cover


def _redact(url: str) -> str:
    """Strip credentials from a connection URL for log lines."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"
