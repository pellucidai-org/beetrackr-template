"""Page-level artifacts produced during a scrape.

Every page can emit one or more files: raw HTML, a markdownified version,
screenshots, recorded videos, etc. ``PageArtifact`` is the canonical data
model describing one such file; ``PageArtifacts`` is an ordered collection
attached to a ``PageStats`` scope.

Typical usage from a scraper::

    from beets.artifacts import (
        html_to_markdown, record_artifact, save_markdown_artifact,
    )

    html = await page.content()
    html_path = save_raw_html_artifact(html, settings, target_name, url)
    md_path   = save_markdown_artifact(html, settings, target_name, url)

    await page.screenshot(path=str(shot_path))
    record_artifact("screenshot", shot_path, media_type="image/png")

The runners in ``airalo.scrapers`` already wire these calls for
you. Anything you push via :func:`record_artifact` ends up:

1. Inline in the persisted record under ``metadata.artifacts.items``.
2. As individual rows in the ``page_artifacts`` SQL table (when
   ``storage.backend == "sql"``), joined to ``scraped_items.record_id`` so
   downstream jobs can query "all artifacts produced by run X".
"""

from __future__ import annotations

from beets.artifacts.markdown import (
    html_to_markdown,
    save_markdown_artifact,
    save_raw_html_artifact,
)
from beets.artifacts.models import PageArtifact, PageArtifacts
from beets.artifacts.registry import (
    guess_media_type,
    record_artifact,
)

__all__ = [
    "PageArtifact",
    "PageArtifacts",
    "guess_media_type",
    "html_to_markdown",
    "record_artifact",
    "save_markdown_artifact",
    "save_raw_html_artifact",
]
