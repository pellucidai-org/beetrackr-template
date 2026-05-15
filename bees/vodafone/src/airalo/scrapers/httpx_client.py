"""Async httpx client with retry + concurrency control.

Use this for static pages where no JS execution is required. Optionally
persists the raw HTML for every URL when ``scraper.save_raw_html`` is on.
Scraped records are written via the configured storage backend
(``settings.storage.backend``: ``jsonl`` / ``sql`` / ...).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from airalo.artifacts import (
    save_markdown_artifact,
    save_raw_html_artifact,
)
from airalo.logging import get_logger
from airalo.scrapers.bs4_parser import parse_with_selectors
from airalo.settings import Settings, TargetConfig, get_settings
from airalo.stats import (
    PageStats,
    extracting,
    page_stats,
    record_request,
    set_complexity,
)
from airalo.storage import get_backend

SCRAPER_KEY = "httpx"

log = get_logger("scrapers.httpx")


def build_client(settings: Settings | None = None) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` configured from settings.

    Wrapped in a Tenacity retry to survive transient OS-level errors (DNS
    blips, fork failures, etc.) when the client is constructed.
    """
    s = settings or get_settings()
    headers = {"User-Agent": s.scraper.user_agent, **s.scraper.default_headers}
    proxies = s.scraper.proxy or None

    for attempt in _client_retry(s):
        with attempt:
            return httpx.AsyncClient(
                headers=headers,
                timeout=s.scraper.request_timeout,
                follow_redirects=True,
                proxy=proxies,
            )
    raise RuntimeError("unreachable")  # pragma: no cover


def _client_retry(s: Settings) -> Any:
    """Sync Tenacity iterator used by :func:`build_client`."""
    from tenacity import Retrying

    return Retrying(
        stop=stop_after_attempt(s.scraper.max_retries),
        wait=wait_exponential(multiplier=s.scraper.retry_backoff, min=1, max=10),
        retry=retry_if_exception_type(OSError),
        before_sleep=before_sleep_log(log, log_level=30),  # WARNING
        reraise=True,
    )


async def fetch_url(url: str, settings: Settings | None = None) -> httpx.Response:
    """Fetch a single URL with retries."""
    s = settings or get_settings()
    async with build_client(s) as client:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(s.scraper.max_retries),
            wait=wait_exponential(multiplier=s.scraper.retry_backoff, min=1, max=30),
            retry=retry_if_exception_type((httpx.HTTPError,)),
            before_sleep=before_sleep_log(log, log_level=30),  # WARNING
            reraise=True,
        ):
            with attempt:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp
        raise RuntimeError("unreachable")  # pragma: no cover


async def run_httpx_target(
    target: TargetConfig,
    settings: Settings,
    output_dir: Path | None = None,
    *,
    job_id: str | None = None,
    scraper_key: str = SCRAPER_KEY,
) -> tuple[int, PageStats]:
    """Fetch every ``start_url``, parse with bs4, persist via the storage backend.

    Each URL runs inside its own ``page_stats`` scope; per-page counters end
    up under ``metadata.stats`` on the persisted record. Returns ``(written,
    session_stats)`` where ``session_stats`` is the additive aggregate over
    every URL processed in this target run and carries the job-level
    ``job_id`` for downstream joins.
    """
    jid = job_id or str(uuid4())
    sem = asyncio.Semaphore(settings.scraper.concurrency)
    session = PageStats(
        target=target.name,
        url=",".join(target.start_urls[:3]),
        job_id=jid,
        scraper_key=scraper_key,
    )

    async def _one(url: str) -> dict[str, Any]:
        async with sem:
            with page_stats(
                target=target.name,
                url=url,
                job_id=jid,
                scraper_key=scraper_key,
            ) as stats:
                resp = await fetch_url(url, settings)
                record_request()
                set_complexity(html=resp.text)

                if settings.scraper.save_raw_html:
                    save_raw_html_artifact(
                        resp.text, settings.scraper.raw_html_dir, target.name, url
                    )
                if settings.scraper.save_markdown:
                    save_markdown_artifact(
                        resp.text, settings.scraper.markdown_dir, target.name, url
                    )

                with extracting():
                    data = parse_with_selectors(resp.text, target.selectors, base_url=url)

                metadata: dict[str, Any] = {
                    "stats": stats.to_dict(),
                    "artifacts": stats.artifacts.to_dict(),
                }
                record: dict[str, Any] = {
                    "job_id": jid,
                    "record_id": stats.record_id,
                    "scraper_key": scraper_key,
                    "url": url,
                    "status": resp.status_code,
                    "data": data,
                    "metadata": metadata,
                }
                session.merge(stats)
                return record

    raw = await asyncio.gather(*[_one(u) for u in target.start_urls], return_exceptions=True)

    records: list[dict[str, Any]] = []
    for r in raw:
        if isinstance(r, BaseException):
            log.error("fetch.failed", error=str(r), job_id=jid)
            continue
        records.append(r)

    backend = get_backend(settings)
    await backend.init()
    try:
        written = await backend.save(target.name, records)
    finally:
        await backend.close()

    session.finalize()
    log.info(
        "httpx.target.done",
        target=target.name,
        job_id=jid,
        scraper_key=scraper_key,
        fetched=len(records),
        written=written,
        backend=backend.name,
        session_page_requests=session.page_requests,
        session_extractions_ok=session.extractions_succeeded,
        session_extractions_failed=session.extractions_failed,
        session_duration_ms=round(session.duration_ms, 1),
        session_extraction_time_ms=round(session.extraction_time_ms, 1),
        session_page_complexity=session.page_complexity,
    )
    return written, session
