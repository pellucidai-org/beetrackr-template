"""Heuristic page-complexity scoring (0 - 100).

The score is a weighted average of normalized signals extracted from raw HTML:

================  ====  =========================================================
Signal            Wt    Saturates at
================  ====  =========================================================
DOM descendants   35    5 000 nodes (typical content site)
``<script>`` tags 20    50 scripts (heavy SPA)
``<iframe>`` tags 10    5 iframes
form controls     10    50 inputs/buttons/selects/textareas
``<form>`` tags    5    5 forms
HTML byte size    20    1 000 KB raw HTML
================  ====  =========================================================

Calibration:
* ~  0 - blank page
* ~ 25 - simple static article (Wikipedia, blog post)
* ~ 50 - typical JS-enabled content site
* ~ 75 - feature-rich e-commerce / SPA dashboard
* ~100 - massive social-feed app with widgets everywhere
"""

from __future__ import annotations


def compute_page_complexity(html: str) -> float:
    """Return a 0 - 100 heuristic complexity score for ``html``.

    Falls back gracefully if BeautifulSoup is unavailable, returning a
    byte-size-only estimate instead of raising.
    """
    if not html:
        return 0.0

    size_kb = len(html) / 1024.0

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return round(min(size_kb / 1000.0, 1.0) * 20.0, 2)

    soup = BeautifulSoup(html, "lxml") if _has_lxml() else BeautifulSoup(html, "html.parser")

    nodes = sum(1 for _ in soup.descendants)
    scripts = len(soup.find_all("script"))
    iframes = len(soup.find_all("iframe"))
    forms = len(soup.find_all("form"))
    inputs = len(soup.find_all(["input", "textarea", "select", "button"]))

    parts: list[tuple[float, float]] = [
        (min(nodes / 5000.0, 1.0), 35.0),
        (min(scripts / 50.0, 1.0), 20.0),
        (min(iframes / 5.0, 1.0), 10.0),
        (min(inputs / 50.0, 1.0), 10.0),
        (min(forms / 5.0, 1.0), 5.0),
        (min(size_kb / 1000.0, 1.0), 20.0),
    ]
    score = sum(frac * weight for frac, weight in parts)
    return round(score, 2)


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False
