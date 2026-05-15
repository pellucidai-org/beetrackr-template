"""Storage backend protocol shared by every adapter.

The persisted record shape::

    {
      "job_id":      "<uuid>",        # shared by every page in one scrape run
      "record_id":   "<uuid>",        # unique per page (1:1 with this row)
      "scraper_key": "httpx",         # which scraper produced this row
      "target":      "example",       # config.yaml target name
      "url":         "https://...",
      "status":      200,
      "scraped_at":  "2026-05-14T...",
      "data":        { ...extracted business data... },
      "metadata":    {
        "stats":     { ...PageStats counters + timings... },
        "artifacts": { "html": "...", "screenshot": "...", "video": "..." }
      }
    }

``job_id`` is the join key for downstream analytics: every page produced by
the same scrape run shares it, so extracted data joins to page-stats / job
monitoring tables 1:N over ``job_id``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _new_id() -> str:
    return str(uuid4())


@dataclass(slots=True)
class ScrapedItem:
    """Canonical record persisted by every backend."""

    target: str
    url: str
    job_id: str = ""
    record_id: str = field(default_factory=_new_id)
    scraper_key: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: int | None = None
    scraped_at: datetime = field(default_factory=_utcnow)

    @classmethod
    def from_record(cls, target: str, record: dict[str, Any]) -> ScrapedItem:
        """Build an item from the raw dict produced by a scraper.

        Accepts both shapes:

        * New (preferred): the scraper supplies ``data``, ``metadata``,
          ``job_id``, ``record_id``, ``scraper_key`` directly.
        * Legacy / flat: any keys outside the reserved set are folded into
          ``data``; ``stats`` + ``artifacts`` are folded into ``metadata``.
        """
        url = str(record.get("url", ""))
        status = record.get("status")
        job_id = str(record.get("job_id") or "")
        record_id = str(record.get("record_id") or _new_id())
        scraper_key = str(record.get("scraper_key") or "")

        data = record.get("data")
        metadata = record.get("metadata")

        # Back-compat: rebuild metadata + data from a flat record.
        if not isinstance(data, dict) or not isinstance(metadata, dict):
            reserved = {
                "url",
                "status",
                "job_id",
                "record_id",
                "scraper_key",
                "data",
                "metadata",
                "stats",
                "artifacts",
            }
            flat_data = {k: v for k, v in record.items() if k not in reserved}
            if not isinstance(data, dict):
                data = flat_data

            md: dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
            stats = record.get("stats")
            artifacts = record.get("artifacts")
            if isinstance(stats, dict) and "stats" not in md:
                md["stats"] = stats
            if isinstance(artifacts, dict) and "artifacts" not in md:
                md["artifacts"] = artifacts
            metadata = md

        # If metadata.stats carries an id but the top-level one is missing,
        # adopt it so the persisted row remains joinable.
        stats_payload = metadata.get("stats") if isinstance(metadata, dict) else None
        if isinstance(stats_payload, dict):
            if not job_id:
                job_id = str(stats_payload.get("job_id") or "")
            if not scraper_key:
                scraper_key = str(stats_payload.get("scraper_key") or "")
            if not record_id and stats_payload.get("record_id"):
                record_id = str(stats_payload["record_id"])

        return cls(
            target=target,
            url=url,
            job_id=job_id,
            record_id=record_id,
            scraper_key=scraper_key,
            status=int(status) if isinstance(status, int) else None,
            data=data if isinstance(data, dict) else {},
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "record_id": self.record_id,
            "scraper_key": self.scraper_key,
            "target": self.target,
            "url": self.url,
            "status": self.status,
            "scraped_at": self.scraped_at.isoformat(),
            "data": self.data,
            "metadata": self.metadata,
        }


@runtime_checkable
class StorageBackend(Protocol):
    """Async persistence contract.

    Implementations should be safe to call ``init`` / ``close`` multiple times.
    """

    name: str

    async def init(self) -> None:
        """One-time setup (open pool, create tables, ...)."""

    async def close(self) -> None:
        """Release resources."""

    async def save(self, target: str, records: Iterable[dict[str, Any]]) -> int:
        """Persist ``records`` for ``target``. Return the count actually written."""
