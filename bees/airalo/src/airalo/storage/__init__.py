"""Pluggable persistence backends for scraped items.

Pick a backend via ``settings.storage.backend``:

* ``jsonl`` - file-per-target JSONL (default).
* ``sql``   - SQLAlchemy async (SQLite, PostgreSQL, Supabase).
* ``mongo`` / ``kafka`` - placeholders, not yet implemented.

Typical usage from a scraper / runner::

    from airalo.settings import get_settings
    from airalo.storage import get_backend

    settings = get_settings()
    backend = get_backend(settings)
    await backend.init()
    try:
        await backend.save("airalo", records)
    finally:
        await backend.close()
"""

from __future__ import annotations

from airalo.settings import Settings, get_settings
from airalo.storage.base import ScrapedItem, StorageBackend
from airalo.storage.jsonl import JSONLBackend


def get_backend(settings: Settings | None = None) -> StorageBackend:
    """Factory returning the storage backend configured in :class:`Settings`."""
    s = settings or get_settings()
    name = s.storage.backend

    if name == "jsonl":
        return JSONLBackend(s)

    if name == "sql":
        # Imported lazily so projects that don't use SQL never pay the
        # SQLAlchemy import cost.
        from airalo.storage.sql import SQLAlchemyBackend

        return SQLAlchemyBackend(s)

    if name in {"mongo", "kafka"}:
        raise NotImplementedError(
            f"Storage backend {name!r} is not implemented yet. "
            "Roadmap: Mongo and Kafka adapters are planned; for now use "
            "'jsonl' or 'sql'."
        )

    raise ValueError(f"Unknown storage backend: {name!r}")


__all__ = [
    "JSONLBackend",
    "ScrapedItem",
    "StorageBackend",
    "get_backend",
]
