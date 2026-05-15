"""Dataclasses describing artifacts produced during a page scrape."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

# Canonical artifact kinds emitted by the bundled scrapers. Custom scrapers
# may use any string they like; these are recognised for indexing / nicer
# pretty-printing.
KIND_HTML = "html"
KIND_MARKDOWN = "markdown"
KIND_SCREENSHOT = "screenshot"
KIND_VIDEO = "video"
KIND_HAR = "har"
KIND_TRACE = "trace"


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class PageArtifact:
    """A single file produced during a page scrape.

    ``path`` is the canonical filesystem location (absolute, or relative to
    the project root). Optional dimensions / duration apply to media:

    * ``width`` / ``height`` for screenshots and videos (pixels);
    * ``duration_ms`` for videos.

    Arbitrary side-channel info goes into ``extra`` (e.g. checksum, codec).
    """

    kind: str
    path: str
    media_type: str = ""
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "width": self.width,
            "height": self.height,
            "duration_ms": self.duration_ms,
            "extra": dict(self.extra),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PageArtifact:
        created = payload.get("created_at")
        if isinstance(created, str):
            created_dt = datetime.fromisoformat(created)
        elif isinstance(created, datetime):
            created_dt = created
        else:
            created_dt = _utcnow()
        return cls(
            kind=str(payload.get("kind", "")),
            path=str(payload.get("path", "")),
            media_type=str(payload.get("media_type", "")),
            size_bytes=payload.get("size_bytes"),
            width=payload.get("width"),
            height=payload.get("height"),
            duration_ms=payload.get("duration_ms"),
            extra=dict(payload.get("extra") or {}),
            created_at=created_dt,
        )


@dataclass(slots=True)
class PageArtifacts:
    """Ordered collection of artifacts produced for one page scrape."""

    items: list[PageArtifact] = field(default_factory=list)

    # ---- mutation --------------------------------------------------------

    def add(self, artifact: PageArtifact) -> PageArtifact:
        self.items.append(artifact)
        return artifact

    def extend(self, others: PageArtifacts | list[PageArtifact]) -> None:
        if isinstance(others, PageArtifacts):
            self.items.extend(others.items)
        else:
            self.items.extend(others)

    # ---- access ----------------------------------------------------------

    def by_kind(self, kind: str) -> list[PageArtifact]:
        return [a for a in self.items if a.kind == kind]

    def first(self, kind: str) -> PageArtifact | None:
        for a in self.items:
            if a.kind == kind:
                return a
        return None

    def paths(self) -> dict[str, str]:
        """``{kind: latest_path}`` convenience mapping (last write wins)."""
        return {a.kind: a.path for a in self.items}

    @property
    def total_bytes(self) -> int:
        return sum(a.size_bytes or 0 for a in self.items)

    def __iter__(self) -> Iterator[PageArtifact]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    # ---- serialization ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.items),
            "total_bytes": self.total_bytes,
            "by_kind": self.paths(),
            "items": [a.to_dict() for a in self.items],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> PageArtifacts:
        if not payload:
            return cls()
        items_payload = payload.get("items") or []
        return cls(items=[PageArtifact.from_dict(p) for p in items_payload])
