"""Helpers for persisting scrape artifacts (raw HTML, screenshots, videos).

Used by both the httpx and Playwright scrapers so the on-disk layout stays
consistent.

Directory layout (when all toggles are enabled):

    <raw_html_dir>/<target>/<slug>.html
    <screenshot_dir>/<target>/<slug>.<png|jpeg>
    <video_dir>/<target>/<slug>.webm
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse

_SAFE_CHARS = re.compile(r"[^a-zA-Z0-9._-]+")
_MAX_SLUG_LEN = 80


def url_slug(url: str) -> str:
    """Produce a deterministic, filesystem-safe slug for a URL.

    Includes a short hash suffix so distinct URLs with the same path don't
    collide on disk.
    """
    parsed = urlparse(url)
    host = parsed.netloc or "unknown"
    path = parsed.path.strip("/") or "index"
    raw = f"{host}_{path}" if path else host
    cleaned = _SAFE_CHARS.sub("-", raw).strip("-._")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{cleaned[:_MAX_SLUG_LEN]}_{digest}"


def artifact_path(root: Path, target: str, url: str, suffix: str) -> Path:
    """Return ``<root>/<target>/<slug><suffix>`` and create parents."""
    out = Path(root) / target / f"{url_slug(url)}{suffix}"
    out.parent.mkdir(parents=True, exist_ok=True)
    return out
