"""HTML -> Markdown conversion + helpers that persist artifacts to disk.

Markdown output is well-suited for LLM-driven post-processing because it
strips presentational markup while preserving structure (headings, lists,
links, tables). We use the ``markdownify`` library with tuned defaults that
play well with most modern web pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from airalo.artifacts.models import (
    KIND_HTML,
    KIND_MARKDOWN,
    PageArtifact,
)
from airalo.artifacts.registry import record_artifact
from airalo.scrapers._artifacts import artifact_path

# Markdownify defaults that strip presentational markup and produce concise
# output. Overridable per-call via ``**opts``.
_MD_DEFAULTS: dict[str, Any] = {
    "heading_style": "ATX",  # `# H1` rather than underline
    "bullets": "-",  # consistent list markers
    "strip": ["script", "style", "noscript"],
    "code_language": "",
    "escape_asterisks": False,
    "escape_underscores": False,
}


def html_to_markdown(html: str, **opts: Any) -> str:
    """Render ``html`` to Markdown using ``markdownify``.

    Pre-cleans the HTML with BeautifulSoup so that scripts, styles, and
    template/comment nodes are dropped before conversion (markdownify's
    ``strip`` argument only removes the opening/closing tags, not the
    nested text content). Extra kwargs override the project defaults
    documented in ``_MD_DEFAULTS``.
    """
    from bs4 import BeautifulSoup, Comment
    from markdownify import markdownify as md

    parser = "lxml"
    try:
        import lxml  # noqa: F401
    except ImportError:  # pragma: no cover
        parser = "html.parser"

    soup = BeautifulSoup(html, parser)
    for tag in soup.find_all(["script", "style", "noscript", "template"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    return md(str(soup), **{**_MD_DEFAULTS, **opts})


def save_raw_html_artifact(
    html: str,
    base_dir: Path,
    target: str,
    url: str,
    *,
    register: bool = True,
) -> PageArtifact | None:
    """Write ``html`` under ``base_dir/<target>/<slug>.html`` and register it.

    Returns the registered :class:`PageArtifact`, or ``None`` if no
    ``page_stats`` scope is active and ``register`` is true.
    """
    path = artifact_path(base_dir, target, url, ".html")
    path.write_text(html, encoding="utf-8")
    if not register:
        return None
    return record_artifact(KIND_HTML, path, media_type="text/html")


def save_markdown_artifact(
    html: str,
    base_dir: Path,
    target: str,
    url: str,
    *,
    register: bool = True,
    **md_opts: Any,
) -> PageArtifact | None:
    """Convert ``html`` to Markdown, write to disk, and register the artifact.

    The output lands at ``base_dir/<target>/<slug>.md``.
    """
    md_text = html_to_markdown(html, **md_opts)
    path = artifact_path(base_dir, target, url, ".md")
    path.write_text(md_text, encoding="utf-8")
    if not register:
        return None
    return record_artifact(KIND_MARKDOWN, path, media_type="text/markdown")
