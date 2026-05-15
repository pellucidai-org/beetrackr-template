"""BeautifulSoup helpers for parsing HTML content."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup


def _make_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def extract_title(html: str) -> str | None:
    soup = _make_soup(html)
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    return h1.get_text(strip=True) if h1 else None


def extract_links(html: str, base_url: str | None = None) -> list[str]:
    soup = _make_soup(html)
    urls: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        urls.append(urljoin(base_url, href) if base_url else href)
    return urls


def parse_with_selectors(
    html: str,
    selectors: dict[str, str] | None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Apply a mapping of name -> CSS-ish selector to extract structured data.

    Supports a tiny subset of Scrapy-style pseudo-selectors:

        "h1::text"          -> first matching element's text
        "a::attr(href)"     -> first matching element's attribute
        "h2"                -> first matching element's text
        "a"                 -> list of texts for every match
    """
    if not selectors:
        return {"title": extract_title(html), "links": extract_links(html, base_url)}

    soup = _make_soup(html)
    out: dict[str, Any] = {}
    for key, selector in selectors.items():
        sel, _, pseudo = selector.partition("::")
        nodes = soup.select(sel)
        if not nodes:
            out[key] = None if not pseudo.startswith("attr") else []
            continue

        if pseudo.startswith("attr(") and pseudo.endswith(")"):
            attr = pseudo[5:-1]
            values = [n.get(attr, "") for n in nodes if n.get(attr)]
            if base_url:
                values = [urljoin(base_url, v) for v in values]
            out[key] = values
        elif pseudo == "text":
            out[key] = nodes[0].get_text(strip=True)
        else:
            out[key] = [n.get_text(strip=True) for n in nodes]
    return out
