"""Context-bound helpers that push :class:`PageArtifact` into the current scope.

These are the ergonomic entry points used by scraper code. They:

* auto-stat the file (``size_bytes``) when it exists on disk;
* infer a sensible ``media_type`` from the extension and artifact kind;
* push the artifact into the current :class:`PageStats` scope so it lands
  in ``metadata.artifacts`` on the persisted record;
* mirror the count to the relevant ``PageStats`` counter (``screenshots``,
  ``videos``) for backward compat with the dashboard view.

Safe to call when no scope is active - returns ``None`` and is a no-op.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from airalo.artifacts.models import (
    KIND_HTML,
    KIND_MARKDOWN,
    KIND_SCREENSHOT,
    KIND_VIDEO,
    PageArtifact,
)

# Kind -> default media_type when the extension doesn't disambiguate.
_DEFAULT_MEDIA_TYPES = {
    KIND_HTML: "text/html",
    KIND_MARKDOWN: "text/markdown",
    KIND_SCREENSHOT: "image/png",
    KIND_VIDEO: "video/webm",
    "har": "application/json",
    "trace": "application/zip",
}


def guess_media_type(path: str | Path, kind: str = "") -> str:
    """Best-effort media_type for ``path`` given an artifact ``kind``.

    Kind-based defaults take precedence over generic octet-stream guesses,
    so e.g. an ``html``-kind artifact saved with a ``.bin`` extension still
    gets ``text/html``.
    """
    mt, _ = mimetypes.guess_type(str(path))
    if mt and mt != "application/octet-stream":
        return mt
    if kind in _DEFAULT_MEDIA_TYPES:
        return _DEFAULT_MEDIA_TYPES[kind]
    return mt or "application/octet-stream"


def record_artifact(
    kind: str,
    path: str | Path,
    *,
    media_type: str = "",
    size_bytes: int | None = None,
    width: int | None = None,
    height: int | None = None,
    duration_ms: float | None = None,
    extra: dict[str, Any] | None = None,
) -> PageArtifact | None:
    """Register an artifact with the current PageStats scope.

    Returns the created :class:`PageArtifact`, or ``None`` if there is no
    active ``page_stats`` scope (in which case this call is a no-op).
    """
    # Lazy import to break the artifacts <-> stats import cycle.
    from airalo.stats import get_current_stats

    s = get_current_stats()
    if s is None:
        return None

    p = Path(path)
    if size_bytes is None:
        try:
            size_bytes = p.stat().st_size
        except OSError:
            size_bytes = None

    artifact = PageArtifact(
        kind=kind,
        path=str(p),
        media_type=media_type or guess_media_type(p, kind),
        size_bytes=size_bytes,
        width=width,
        height=height,
        duration_ms=duration_ms,
        extra=dict(extra or {}),
    )
    s.artifacts.add(artifact)

    # Mirror to the legacy counters so dashboards keep working.
    if kind == KIND_SCREENSHOT:
        s.record_screenshot()
    elif kind == KIND_VIDEO:
        s.record_video()

    return artifact
