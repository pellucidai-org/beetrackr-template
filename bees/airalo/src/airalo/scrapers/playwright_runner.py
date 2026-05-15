"""Playwright-based scraper for JS-rendered pages.

Run ``playwright install`` once before using.

Configurable side-effects (all opt-in, all driven by ``config.yaml`` →
``playwright.*`` / ``scraper.*``):

* ``playwright.record_video``      - save a ``.webm`` per page navigation.
* ``playwright.screenshot``        - save a ``.png``/``.jpeg`` per page.
* ``scraper.save_raw_html``        - save the post-render HTML per page.

Browser launches are wrapped in a Tenacity retry to survive transient failures
(slow disks, busy hosts, kernel quirks with new browser processes).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, async_playwright
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from airalo.artifacts import (
    record_artifact,
    save_markdown_artifact,
    save_raw_html_artifact,
)
from airalo.artifacts.models import KIND_SCREENSHOT, KIND_VIDEO
from airalo.logging import get_logger
from airalo.scrapers._artifacts import artifact_path
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

SCRAPER_KEY = "playwright"

log = get_logger("scrapers.playwright")


# ---------------------------------------------------------------------------
# Resilient launch / context creation
# ---------------------------------------------------------------------------


async def _launch_browser(pw: Any, settings: Settings) -> Browser:
    """Launch a browser with Tenacity-driven retries."""
    pw_cfg = settings.playwright
    browser_type = getattr(pw, pw_cfg.browser)

    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(pw_cfg.launch_max_retries),
        wait=wait_exponential(multiplier=pw_cfg.launch_retry_backoff, min=1, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(log, log_level=30),  # WARNING
        reraise=True,
    ):
        with attempt:
            return await browser_type.launch(headless=pw_cfg.headless)
    raise RuntimeError("unreachable")  # pragma: no cover


async def _new_context(
    browser: Browser, settings: Settings, *, target: TargetConfig
) -> BrowserContext:
    """Create a context, wiring up video recording and resource blocking."""
    pw_cfg = settings.playwright
    options: dict[str, Any] = {
        "user_agent": settings.scraper.user_agent,
        "viewport": pw_cfg.viewport,
    }

    if pw_cfg.record_video:
        video_dir = pw_cfg.record_video_dir / target.name
        video_dir.mkdir(parents=True, exist_ok=True)
        options["record_video_dir"] = str(video_dir)
        options["record_video_size"] = pw_cfg.record_video_size

    context = await browser.new_context(**options)

    blocked = set(pw_cfg.block_resource_types)
    if blocked:

        async def _route(route: Any, request: Any) -> None:
            if request.resource_type in blocked:
                await route.abort()
            else:
                await route.continue_()

        await context.route("**/*", _route)

    return context


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_playwright_target(
    target: TargetConfig,
    settings: Settings | None = None,
    *,
    job_id: str | None = None,
    scraper_key: str = SCRAPER_KEY,
) -> tuple[int, PageStats]:
    """Scrape ``target`` with Playwright.

    Returns ``(written, session_stats)``. ``session_stats`` carries the
    job-level ``job_id`` so downstream consumers can join records to the
    scrape run that produced them.
    """
    s = settings or get_settings()
    pw_cfg = s.playwright
    scraper_cfg = s.scraper
    jid = job_id or str(uuid4())

    results: list[dict[str, Any]] = []
    session = PageStats(
        target=target.name,
        url=",".join(target.start_urls[:3]),
        job_id=jid,
        scraper_key=scraper_key,
    )

    async with async_playwright() as pw:
        browser = await _launch_browser(pw, s)

        for url in target.start_urls:
            with page_stats(
                target=target.name,
                url=url,
                job_id=jid,
                scraper_key=scraper_key,
            ) as stats:
                data: dict[str, Any] = {}
                error: str | None = None
                # When recording video we need a fresh context per URL so each
                # navigation yields its own .webm.
                context = await _new_context(browser, s, target=target)
                page = await context.new_page()
                page.set_default_navigation_timeout(pw_cfg.navigation_timeout_ms)
                status: int | None = None
                viewport = pw_cfg.viewport
                video_size = pw_cfg.record_video_size

                try:
                    response = await page.goto(url, wait_until="domcontentloaded")
                    record_request()
                    if response is not None:
                        status = response.status
                    html = await page.content()
                    set_complexity(html=html)

                    if scraper_cfg.save_raw_html:
                        save_raw_html_artifact(html, scraper_cfg.raw_html_dir, target.name, url)
                    if scraper_cfg.save_markdown:
                        save_markdown_artifact(html, scraper_cfg.markdown_dir, target.name, url)

                    if pw_cfg.screenshot:
                        suffix = f".{pw_cfg.screenshot_format}"
                        shot_path = artifact_path(pw_cfg.screenshot_dir, target.name, url, suffix)
                        await page.screenshot(
                            path=str(shot_path),
                            full_page=pw_cfg.screenshot_full_page,
                            type=pw_cfg.screenshot_format,
                        )
                        record_artifact(
                            KIND_SCREENSHOT,
                            shot_path,
                            media_type=f"image/{pw_cfg.screenshot_format}",
                            width=viewport.get("width"),
                            height=viewport.get("height"),
                            extra={"full_page": pw_cfg.screenshot_full_page},
                        )

                    with extracting():
                        data = parse_with_selectors(html, target.selectors, base_url=url)
                except Exception as exc:
                    error = str(exc)
                    log.error(
                        "playwright.page.failed",
                        url=url,
                        error=error,
                        job_id=jid,
                    )
                finally:
                    video = page.video if pw_cfg.record_video else None
                    await context.close()  # finalises video recording

                    if video is not None:
                        try:
                            video_path = await video.path()
                            record_artifact(
                                KIND_VIDEO,
                                video_path,
                                media_type="video/webm",
                                width=video_size.get("width"),
                                height=video_size.get("height"),
                            )
                        except Exception as exc:  # pragma: no cover
                            log.warning("playwright.video.path_failed", error=str(exc))

                if error is not None:
                    data = {"error": error}
                metadata: dict[str, Any] = {
                    "stats": stats.to_dict(),
                    "artifacts": stats.artifacts.to_dict(),
                }
                result: dict[str, Any] = {
                    "job_id": jid,
                    "record_id": stats.record_id,
                    "scraper_key": scraper_key,
                    "url": url,
                    "status": status,
                    "data": data,
                    "metadata": metadata,
                }
                results.append(result)
                session.merge(stats)
                log.info(
                    "playwright.page.done",
                    url=url,
                    job_id=jid,
                    record_id=stats.record_id,
                    artifacts=[a.kind for a in stats.artifacts],
                )

        await browser.close()

    backend = get_backend(s)
    await backend.init()
    try:
        written = await backend.save(target.name, results)
    finally:
        await backend.close()

    session.finalize()
    log.info(
        "playwright.target.done",
        target=target.name,
        job_id=jid,
        scraper_key=scraper_key,
        fetched=len(results),
        written=written,
        backend=backend.name,
        session_page_requests=session.page_requests,
        session_screenshots=session.screenshots,
        session_videos=session.videos,
        session_extractions_ok=session.extractions_succeeded,
        session_extractions_failed=session.extractions_failed,
        session_duration_ms=round(session.duration_ms, 1),
        session_extraction_time_ms=round(session.extraction_time_ms, 1),
        session_page_complexity=session.page_complexity,
    )
    return written, session
