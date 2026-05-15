"""Tests for the BeautifulSoup helpers."""

from __future__ import annotations

from beets.scrapers.bs4_parser import (
    extract_links,
    extract_title,
    parse_with_selectors,
)

HTML = """
<html>
  <head><title>Hello</title></head>
  <body>
    <h1>Header</h1>
    <a href="/about">About</a>
    <a href="https://example.com/contact">Contact</a>
    <a href="#section">Ignore me</a>
  </body>
</html>
"""


def test_extract_title() -> None:
    assert extract_title(HTML) == "Hello"


def test_extract_links_resolves_relative() -> None:
    links = extract_links(HTML, base_url="https://example.com")
    assert "https://example.com/about" in links
    assert "https://example.com/contact" in links
    assert not any(u.endswith("#section") for u in links)


def test_parse_with_selectors() -> None:
    data = parse_with_selectors(
        HTML,
        {"title": "h1::text", "links": "a::attr(href)"},
        base_url="https://example.com",
    )
    assert data["title"] == "Header"
    assert "https://example.com/about" in data["links"]
