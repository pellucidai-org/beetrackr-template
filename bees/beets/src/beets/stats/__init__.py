"""Page-level metrics for scrapers.

A ``PageStats`` instance counts every interesting event during a single page
scrape: HTTP requests, clicks, screenshots, videos, LLM calls + token usage,
extraction outcomes, and a heuristic DOM-complexity score.

Typical usage from a scraper::

    from beets.stats import (
        page_stats, record_extraction, record_request, set_complexity,
    )

    async def scrape_one(url: str) -> dict:
        with page_stats(target="airalo", url=url) as stats:
            resp = await fetch_url(url)
            record_request()
            set_complexity(html=resp.text)
            try:
                data = parse(resp.text)
                record_extraction(success=True)
            except Exception:
                record_extraction(success=False)
                raise
            return {**data, "stats": stats.to_dict()}

Helpers in this module are safe to call when no scope is open — they no-op,
so library code (an LLM client, a Playwright wrapper, ...) can always emit
stats without worrying about whether it's running inside a scrape session.
"""

from __future__ import annotations

from beets.stats.complexity import compute_page_complexity
from beets.stats.page_stats import (
    PageStats,
    extracting,
    get_current_stats,
    page_stats,
    record_click,
    record_extraction,
    record_llm_call,
    record_request,
    record_screenshot,
    record_video,
    set_complexity,
)

__all__ = [
    "PageStats",
    "compute_page_complexity",
    "extracting",
    "get_current_stats",
    "page_stats",
    "record_click",
    "record_extraction",
    "record_llm_call",
    "record_request",
    "record_screenshot",
    "record_video",
    "set_complexity",
]
