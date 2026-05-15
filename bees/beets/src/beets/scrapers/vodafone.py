"""Vodafone Travel eSIM scraper (https://travel.vodafone.com/).

The site is a client-rendered SPA. This module uses Playwright to fetch HTML,
then parses:

1. ``/our-destinations`` - destination slugs from internal links.
2. ``/our-destinations/{slug}`` - eSIM plans from ``application/ld+json``
   ``Product`` blocks (one offer per ``productID``, preferred currency GBP).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import uuid4

from bs4 import BeautifulSoup
from playwright.async_api import Browser, Page, async_playwright

from beets.artifacts import save_markdown_artifact, save_raw_html_artifact
from beets.logging import get_logger
from beets.scrapers.playwright_runner import _launch_browser
from beets.settings import Settings, get_settings
from beets.stats import (
    PageStats,
    extracting,
    page_stats,
    record_request,
    set_complexity,
)
from beets.storage import get_backend

SCRAPER_KEY = "vodafone"

log = get_logger("scrapers.vodafone")

BASE_URL = "https://travel.vodafone.com"
INDEX_URL = f"{BASE_URL}/our-destinations"

# Regional hub pages (not individual countries).
REGION_SLUGS = frozenset(
    {
        "africa",
        "asia",
        "caribbean",
        "europe",
        "latin-america",
        "middle-east",
        "north-america",
        "oceania",
        "uefachampionsleague",
    }
)

_PRODUCT_ID_RE = re.compile(
    r"^(?:(?P<country>[A-Z]{3})_)?"
    r"(?:(?P<gb>\d+)GB|UNLGB?)"
    r"(?P<days>\d+)"
    r"D[a-z]?$",
    re.IGNORECASE,
)

_PREFERRED_CURRENCIES = ("GBP", "EUR", "USD")


@dataclass(slots=True)
class DestinationEntry:
    """One destination on the index page."""

    name: str
    slug: str
    url: str
    is_region: bool = False


@dataclass(slots=True)
class Package:
    name: str
    product_id: str
    price: float
    currency: str
    data: str
    data_gb: float | None
    unlimited: bool
    validity_days: int
    prices_by_currency: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class DestinationDetail:
    name: str
    slug: str
    url: str
    packages: list[Package] = field(default_factory=list)


def _slug_from_href(href: str) -> str | None:
    path = urlparse(href).path.rstrip("/")
    if "/our-destinations/" not in path:
        return None
    slug = path.rsplit("/", 1)[-1]
    if not slug or slug == "our-destinations":
        return None
    return slug


def parse_destinations_index(
    html: str,
    *,
    base_url: str = BASE_URL,
    countries_only: bool = False,
) -> list[DestinationEntry]:
    """Extract destination links from a rendered ``/our-destinations`` page."""
    soup = BeautifulSoup(html, "lxml")
    by_slug: dict[str, DestinationEntry] = {}

    for a in soup.select('a[href*="/our-destinations/"]'):
        href = a.get("href", "")
        slug = _slug_from_href(urljoin(base_url, href))
        if slug is None:
            continue
        is_region = slug in REGION_SLUGS
        if countries_only and is_region:
            continue

        name = a.get_text(" ", strip=True) or slug.replace("-", " ").title()
        entry = DestinationEntry(
            name=name,
            slug=slug,
            url=f"{base_url}/our-destinations/{slug}",
            is_region=is_region,
        )
        by_slug.setdefault(slug, entry)

    return sorted(by_slug.values(), key=lambda e: e.slug)


def _parse_product_id(product_id: str) -> tuple[str, float | None, bool, int]:
    pid = product_id.strip()
    m = _PRODUCT_ID_RE.match(pid)
    if m:
        if m.group("gb"):
            gb = float(m.group("gb"))
            label = f"{int(gb) if gb.is_integer() else gb} GB"
            return label, gb, False, int(m.group("days"))
        return "Unlimited", None, True, int(m.group("days"))
    if "UNL" in pid.upper():
        days_m = re.search(r"(\d+)D", pid, re.IGNORECASE)
        days = int(days_m.group(1)) if days_m else 0
        return "Unlimited", None, True, days
    gb_m = re.search(r"(\d+(?:\.\d+)?)GB", pid, re.IGNORECASE)
    days_m = re.search(r"(\d+)D", pid, re.IGNORECASE)
    if gb_m:
        gb = float(gb_m.group(1))
        days = int(days_m.group(1)) if days_m else 0
        label = f"{int(gb) if gb.is_integer() else gb} GB"
        return label, gb, False, days
    return pid, None, False, 0


def _pick_offer_price(offers: list[dict[str, Any]]) -> tuple[float, str, dict[str, float]]:
    by_currency: dict[str, float] = {}
    for offer in offers:
        currency = str(offer.get("priceCurrency", "")).upper()
        price = offer.get("price")
        if currency and isinstance(price, (int, float)):
            by_currency[currency] = float(price)
    for currency in _PREFERRED_CURRENCIES:
        if currency in by_currency:
            return by_currency[currency], currency, by_currency
    if by_currency:
        cur = next(iter(by_currency))
        return by_currency[cur], cur, by_currency
    return 0.0, "", by_currency


def parse_destination(
    html: str,
    *,
    slug: str,
    url: str,
    preferred_currencies: tuple[str, ...] = _PREFERRED_CURRENCIES,
) -> DestinationDetail:
    """Parse eSIM plans from JSON-LD ``Product`` data on a destination page."""
    soup = BeautifulSoup(html, "lxml")
    name_el = soup.find("h1")
    name = name_el.get_text(strip=True) if name_el else slug.replace("-", " ").title()

    offers_by_pid: dict[str, list[dict[str, Any]]] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        if data.get("@type") != "Product":
            continue
        for offer in data.get("offers", []):
            if offer.get("@type") != "Offer":
                continue
            pid = str(offer.get("productID", "")).strip()
            if pid:
                offers_by_pid.setdefault(pid, []).append(offer)

    packages: list[Package] = []
    for pid, offers in sorted(offers_by_pid.items()):
        sample = offers[0]
        plan_name = str(sample.get("name", pid))
        data_label, data_gb, unlimited, validity_days = _parse_product_id(pid)
        price, currency, all_prices = _pick_offer_price(offers)
        if preferred_currencies:
            for cur in preferred_currencies:
                if cur in all_prices:
                    price, currency = all_prices[cur], cur
                    break
        packages.append(
            Package(
                name=plan_name,
                product_id=pid,
                price=price,
                currency=currency,
                data=data_label,
                data_gb=data_gb,
                unlimited=unlimited,
                validity_days=validity_days,
                prices_by_currency=all_prices,
            )
        )

    return DestinationDetail(name=name, slug=slug, url=url, packages=packages)


async def _fetch_rendered_html(
    page: Page,
    url: str,
    *,
    settings: Settings,
    settle_ms: int = 2000,
    nav_lock: asyncio.Lock | None = None,
) -> tuple[str, int]:
    pw_cfg = settings.playwright
    page.set_default_navigation_timeout(pw_cfg.navigation_timeout_ms)

    async def _go() -> tuple[str, int]:
        response = await page.goto(url, wait_until="domcontentloaded")
        if settle_ms > 0:
            await page.wait_for_timeout(settle_ms)
        html = await page.content()
        status = response.status if response is not None else 200
        return html, status

    if nav_lock is None:
        return await _go()
    async with nav_lock:
        return await _go()


async def scrape_vodafone(
    settings: Settings | None = None,
    *,
    target_name: str = "vodafone",
    limit: int | None = None,
    job_id: str | None = None,
    scraper_key: str = SCRAPER_KEY,
    countries_only: bool = True,
) -> tuple[int, PageStats]:
    """Scrape Vodafone Travel destinations and persist one record per destination."""
    s = settings or get_settings()
    jid = job_id or str(uuid4())
    session = PageStats(
        target=target_name,
        url=INDEX_URL,
        job_id=jid,
        scraper_key=scraper_key,
    )

    async with async_playwright() as pw:
        browser: Browser = await _launch_browser(pw, s)
        context = await browser.new_context(user_agent=s.scraper.user_agent)
        page = await context.new_page()
        nav_lock = asyncio.Lock()

        with page_stats(
            target=target_name,
            url=INDEX_URL,
            job_id=jid,
            scraper_key=scraper_key,
        ) as idx_stats:
            log.info("vodafone.index.fetching", url=INDEX_URL, job_id=jid)
            index_html, index_status = await _fetch_rendered_html(
                page, INDEX_URL, settings=s, nav_lock=nav_lock
            )
            record_request()
            set_complexity(html=index_html)
            if s.scraper.save_raw_html:
                save_raw_html_artifact(index_html, s.scraper.raw_html_dir, target_name, INDEX_URL)
            if s.scraper.save_markdown:
                save_markdown_artifact(index_html, s.scraper.markdown_dir, target_name, INDEX_URL)
            with extracting():
                entries = parse_destinations_index(index_html, countries_only=countries_only)
            _ = index_status
        session.merge(idx_stats)

        if limit is not None:
            entries = entries[:limit]
        log.info("vodafone.index.parsed", destinations=len(entries), job_id=jid)

        sem = asyncio.Semaphore(max(1, s.scraper.concurrency))

        async def _one(entry: DestinationEntry) -> tuple[dict[str, Any] | None, PageStats]:
            async with sem:
                with page_stats(
                    target=target_name,
                    url=entry.url,
                    job_id=jid,
                    scraper_key=scraper_key,
                ) as ps:
                    try:
                        html, status = await _fetch_rendered_html(
                            page, entry.url, settings=s, nav_lock=nav_lock
                        )
                        record_request()
                        set_complexity(html=html)
                        if s.scraper.save_raw_html:
                            save_raw_html_artifact(
                                html, s.scraper.raw_html_dir, target_name, entry.url
                            )
                        if s.scraper.save_markdown:
                            save_markdown_artifact(
                                html, s.scraper.markdown_dir, target_name, entry.url
                            )
                        with extracting():
                            detail = parse_destination(html, slug=entry.slug, url=entry.url)
                    except Exception as exc:
                        log.error(
                            "vodafone.destination.failed",
                            slug=entry.slug,
                            error=str(exc),
                            job_id=jid,
                        )
                        return None, ps

                    starting = min(
                        (p.price for p in detail.packages if p.price > 0),
                        default=None,
                    )
                    data = {
                        "name": detail.name,
                        "slug": entry.slug,
                        "is_region": entry.is_region,
                        "starting_price": starting,
                        "package_count": len(detail.packages),
                        "packages": [asdict(p) for p in detail.packages],
                    }
                    record = {
                        "job_id": jid,
                        "record_id": ps.record_id,
                        "scraper_key": scraper_key,
                        "url": entry.url,
                        "status": status,
                        "data": data,
                        "metadata": {
                            "stats": ps.to_dict(),
                            "artifacts": ps.artifacts.to_dict(),
                        },
                    }
                    log.info(
                        "vodafone.destination.done",
                        slug=entry.slug,
                        packages=len(detail.packages),
                        job_id=jid,
                        record_id=ps.record_id,
                    )
                    return record, ps

        pairs = await asyncio.gather(*(_one(e) for e in entries))
        await context.close()
        await browser.close()

    records: list[dict[str, Any]] = []
    for r, ps in pairs:
        session.merge(ps)
        if r is not None:
            records.append(r)

    backend = get_backend(s)
    await backend.init()
    try:
        written = await backend.save(target_name, records)
    finally:
        await backend.close()

    session.finalize()
    log.info(
        "vodafone.done",
        job_id=jid,
        scraper_key=scraper_key,
        destinations=len(entries),
        succeeded=len(records),
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
