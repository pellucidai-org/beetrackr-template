"""Tests for airalo.artifacts: data model, registry, markdown."""

from __future__ import annotations

from pathlib import Path

import pytest

from airalo.artifacts import (
    PageArtifact,
    PageArtifacts,
    html_to_markdown,
    record_artifact,
    save_markdown_artifact,
    save_raw_html_artifact,
)
from airalo.artifacts.models import (
    KIND_HTML,
    KIND_MARKDOWN,
    KIND_SCREENSHOT,
    KIND_VIDEO,
)
from airalo.artifacts.registry import guess_media_type
from airalo.stats import page_stats

# ---------------------------------------------------------------------------
# PageArtifact / PageArtifacts dataclasses
# ---------------------------------------------------------------------------


def test_page_artifact_round_trip() -> None:
    a = PageArtifact(
        kind=KIND_SCREENSHOT,
        path="/tmp/a.png",
        media_type="image/png",
        size_bytes=1234,
        width=800,
        height=600,
        extra={"full_page": True},
    )
    payload = a.to_dict()
    b = PageArtifact.from_dict(payload)
    assert b.kind == a.kind
    assert b.path == a.path
    assert b.media_type == a.media_type
    assert b.size_bytes == 1234
    assert b.width == 800
    assert b.height == 600
    assert b.extra == {"full_page": True}


def test_page_artifacts_collection_operations() -> None:
    coll = PageArtifacts()
    assert not coll
    coll.add(PageArtifact(kind=KIND_HTML, path="/tmp/a.html", size_bytes=100))
    coll.add(PageArtifact(kind=KIND_MARKDOWN, path="/tmp/a.md", size_bytes=50))
    coll.add(PageArtifact(kind=KIND_VIDEO, path="/tmp/a.webm", size_bytes=2048))

    assert len(coll) == 3
    assert coll.total_bytes == 100 + 50 + 2048
    assert coll.first(KIND_HTML).path == "/tmp/a.html"  # type: ignore[union-attr]
    assert coll.by_kind(KIND_MARKDOWN) == [coll.items[1]]
    assert coll.paths() == {
        "html": "/tmp/a.html",
        "markdown": "/tmp/a.md",
        "video": "/tmp/a.webm",
    }


def test_page_artifacts_to_dict_shape() -> None:
    coll = PageArtifacts()
    coll.add(PageArtifact(kind=KIND_HTML, path="/tmp/a.html", size_bytes=10))
    d = coll.to_dict()
    assert d["count"] == 1
    assert d["total_bytes"] == 10
    assert d["by_kind"] == {"html": "/tmp/a.html"}
    assert len(d["items"]) == 1
    assert d["items"][0]["kind"] == "html"


def test_page_artifacts_from_dict_round_trip() -> None:
    src = PageArtifacts()
    src.add(PageArtifact(kind=KIND_HTML, path="/tmp/a.html"))
    src.add(PageArtifact(kind=KIND_VIDEO, path="/tmp/a.webm", duration_ms=1500.0))

    rehydrated = PageArtifacts.from_dict(src.to_dict())
    assert len(rehydrated) == 2
    assert rehydrated.first(KIND_VIDEO).duration_ms == 1500.0  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# guess_media_type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,kind,expected",
    [
        ("/tmp/foo.html", "", "text/html"),
        ("/tmp/foo.md", "", "text/markdown"),
        ("/tmp/foo.png", "", "image/png"),
        ("/tmp/foo.webm", "", "video/webm"),
        ("/tmp/foo.bin", KIND_HTML, "text/html"),  # fallback by kind
        ("/tmp/foo.bin", "unknown", "application/octet-stream"),
    ],
)
def test_guess_media_type(path: str, kind: str, expected: str) -> None:
    assert guess_media_type(path, kind) == expected


# ---------------------------------------------------------------------------
# record_artifact + scope integration
# ---------------------------------------------------------------------------


def test_record_artifact_outside_scope_is_noop() -> None:
    a = record_artifact(KIND_HTML, "/tmp/never.html")
    assert a is None


def test_record_artifact_attaches_to_current_stats(tmp_path: Path) -> None:
    f = tmp_path / "snapshot.png"
    f.write_bytes(b"\x89PNG" + b"\x00" * 100)

    with page_stats(target="t", url="u") as s:
        a = record_artifact(KIND_SCREENSHOT, f, width=800, height=600, extra={"full_page": True})

    assert a is not None
    assert a.size_bytes == f.stat().st_size
    assert a.media_type == "image/png"
    assert a.width == 800 and a.height == 600
    assert a.extra == {"full_page": True}
    assert next(iter(s.artifacts)) is a


def test_record_artifact_increments_screenshot_and_video_counters(
    tmp_path: Path,
) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    vid = tmp_path / "rec.webm"
    vid.write_bytes(b"\x1aEdz")  # webm magic

    with page_stats(target="t", url="u") as s:
        record_artifact(KIND_SCREENSHOT, shot)
        record_artifact(KIND_VIDEO, vid)

    assert s.screenshots == 1
    assert s.videos == 1
    kinds = [a.kind for a in s.artifacts]
    assert kinds == [KIND_SCREENSHOT, KIND_VIDEO]


def test_merge_combines_artifacts() -> None:
    with page_stats(target="t", url="a") as a:
        record_artifact(KIND_HTML, "/tmp/a.html")
    with page_stats(target="t", url="b") as b:
        record_artifact(KIND_HTML, "/tmp/b.html")

    a.merge(b)
    assert [art.path for art in a.artifacts] == ["/tmp/a.html", "/tmp/b.html"]


# ---------------------------------------------------------------------------
# html_to_markdown + save_*_artifact
# ---------------------------------------------------------------------------


def test_html_to_markdown_basic() -> None:
    html = (
        "<html><body>"
        "<h1>Title</h1>"
        "<script>secret()</script>"
        "<p>Hello <strong>world</strong>.</p>"
        "<ul><li>a</li><li>b</li></ul>"
        "</body></html>"
    )
    md = html_to_markdown(html).strip()
    assert "# Title" in md
    assert "Hello **world**." in md
    assert "- a" in md and "- b" in md
    assert "secret()" not in md  # <script> stripped


def test_save_markdown_artifact_writes_file_and_registers(tmp_path: Path) -> None:
    html = "<html><body><h1>X</h1><p>y</p></body></html>"
    with page_stats(target="t", url="https://example.com/page") as s:
        a = save_markdown_artifact(html, tmp_path, "t", "https://example.com/page")

    assert a is not None
    assert a.kind == KIND_MARKDOWN
    assert a.path.endswith(".md")
    assert Path(a.path).read_text(encoding="utf-8").startswith("# X")
    assert a.size_bytes is not None and a.size_bytes > 0
    assert s.artifacts.first(KIND_MARKDOWN) is a


def test_save_raw_html_artifact_writes_file_and_registers(tmp_path: Path) -> None:
    html = "<html><body>raw</body></html>"
    with page_stats(target="t", url="https://example.com/page") as s:
        a = save_raw_html_artifact(html, tmp_path, "t", "https://example.com/page")

    assert a is not None
    assert a.kind == KIND_HTML
    assert Path(a.path).read_text(encoding="utf-8") == html
    assert s.artifacts.first(KIND_HTML) is a
