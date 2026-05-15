"""SQLAlchemy ORM models for the SQL storage backend.

Uses SQLAlchemy 2.0 declarative + typed ``Mapped`` columns. ``data`` and
``metadata_`` are stored as JSON, which works portably across SQLite (JSON1)
and PostgreSQL (native JSONB on Postgres / Supabase).

Indexed columns ``job_id``, ``record_id``, and ``scraper_key`` are intended
for downstream joins / job monitoring dashboards:

* ``job_id``: every row created by one scrape run shares it - join data to
  page-stats and aggregate per-run metrics.
* ``record_id``: unique per row; usable as a stable external reference.
* ``scraper_key``: filter by scraper implementation.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Project-wide declarative base. Extend with more tables as needed."""


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class ScrapedItemORM(Base):
    """Canonical scraped-item row."""

    __tablename__ = "scraped_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    record_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    scraper_key: Mapped[str] = mapped_column(String(64), index=True, default="")
    target: Mapped[str] = mapped_column(String(128), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # ``metadata`` is reserved on DeclarativeBase, so the python attribute is
    # ``metadata_`` while the SQL column stays ``metadata``.
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    __table_args__ = (
        Index("ix_scraped_items_job_record", "job_id", "record_id"),
        Index("ix_scraped_items_target_scraped_at", "target", "scraped_at"),
        Index("ix_scraped_items_target_url", "target", "url"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<ScrapedItem id={self.id} job={self.job_id} target={self.target!r} url={self.url!r}>"
        )


class PageArtifactORM(Base):
    """One row per file produced for a page (html, markdown, screenshot, video, ...).

    ``record_id`` joins to ``scraped_items.record_id`` (1:N). ``job_id`` is
    duplicated for direct "all artifacts in run X" queries without an extra
    join. Combined with the index on ``kind`` this lets dashboards answer
    things like "give me every video file produced by job ``abc`` for target
    ``airalo``" in a single indexed lookup.
    """

    __tablename__ = "page_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True, default="")
    target: Mapped[str] = mapped_column(String(128), index=True, default="")
    kind: Mapped[str] = mapped_column(String(32), index=True)
    path: Mapped[str] = mapped_column(String(2048))
    media_type: Mapped[str] = mapped_column(String(128), default="")
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    __table_args__ = (
        Index("ix_page_artifacts_record_kind", "record_id", "kind"),
        Index("ix_page_artifacts_job_kind", "job_id", "kind"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debug only
        return (
            f"<PageArtifact id={self.id} record={self.record_id} "
            f"kind={self.kind!r} path={self.path!r}>"
        )
