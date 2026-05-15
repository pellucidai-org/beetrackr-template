"""Airalo-specific scraper.

Two-phase pipeline:

1.  Fetch ``https://www.airalo.com/all-esim`` and enumerate every country card
    (name, slug, flag image, starting price).
2.  Fetch each ``/{slug}-esim`` page concurrently and extract the package list
    from each ``aria-label="Select X GB - Y days for £Z."`` button.

Both phases reuse :func:`airalo.scrapers.httpx_client.fetch_url`, so HTTP
retries / timeouts / user-agent / proxy come from the project ``Settings``.
Results land in the configured storage backend
(``storage.backend``: ``jsonl`` / ``sql`` / ...).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

from bs4 import BeautifulSoup

from airalo.artifacts import save_markdown_artifact, save_raw_html_artifact
from airalo.logging import get_logger
from airalo.scrapers.httpx_client import fetch_url
from airalo.settings import Settings, get_settings
from airalo.stats import (
    PageStats,
    extracting,
    page_stats,
    record_request,
    set_complexity,
)
from airalo.storage import get_backend

SCRAPER_KEY = "airalo"

log = get_logger("scrapers.airalo")

BASE_URL = "https://www.airalo.com"
INDEX_URL = f"{BASE_URL}/all-esim"

# Each package button carries:
#   aria-label="Select 1 GB - 3 days for £3.50."
#   aria-label="Select Unlimited - 7 days for $25.00."
_PACKAGE_RE = re.compile(
    r"Select\s+"
    r"(?:"
    r"(?P<size>\d+(?:\.\d+)?)\s*(?P<unit>GB|MB)"  # finite data quota
    r"|"
    r"(?P<unlimited>Unlimited)"  # or unlimited tier
    r")"
    r"\s*-\s*"
    r"(?P<validity>\d+)\s*days?"
    r"\s+for\s+"
    r"(?P<currency>[\$£€])\s*(?P<price>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CountryEntry:
    """One card on the ``/all-esim`` index."""

    name: str
    slug: str
    url: str
    flag_url: str | None = None
    starting_price: str | None = None  # raw text, currency varies by locale


@dataclass(slots=True)
class Package:
    data: str  # display text, e.g. "1 GB" or "Unlimited"
    data_gb: float | None  # normalised to GB (None if unlimited)
    unlimited: bool
    validity_days: int
    currency: str  # "$" | "£" | "€"
    price: float
    aria_label: str  # original label for debugging / audit


@dataclass(slots=True)
class CountryDetail:
    """Parsed country page."""

    name: str
    slug: str
    url: str
    packages: list[Package] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Parsers (pure functions, easy to unit-test against saved HTML)
# ---------------------------------------------------------------------------


def parse_index(html: str, *, base_url: str = BASE_URL) -> list[CountryEntry]:
    """Extract every country card from the ``/all-esim`` HTML.

    The page renders the same country up to twice: once as a "Popular
    locations" carousel chip (no price) and once in the main grid (with a
    starting price + flag). We dedupe by slug and prefer the priced entry.
    """
    soup = BeautifulSoup(html, "lxml")
    by_slug: dict[str, CountryEntry] = {}

    for a in soup.select('a[href$="-esim"][aria-label^="Select "]'):
        href = a.get("href", "")
        if not href.startswith("/"):
            continue
        slug = href.rstrip("/").rsplit("/", 1)[-1].removesuffix("-esim")

        name = (a.get("aria-label") or "").removeprefix("Select ").strip()
        if not name:
            title_el = a.select_one('[data-testid="locations-details_title"]')
            name = title_el.get_text(strip=True) if title_el else slug.replace("-", " ").title()

        img = a.find("img")
        flag_url = img.get("src") if img else None

        price_el = a.select_one('[data-testid="price_amount"]')
        starting_price = price_el.get_text(" ", strip=True) if price_el else None

        candidate = CountryEntry(
            name=name,
            slug=slug,
            url=urljoin(base_url, href),
            flag_url=flag_url,
            starting_price=starting_price,
        )

        existing = by_slug.get(slug)
        if existing is None:
            by_slug[slug] = candidate
            continue

        # Already have one - upgrade if the new card has a price/flag and the
        # old one doesn't.
        score = (bool(candidate.starting_price), bool(candidate.flag_url))
        prev_score = (bool(existing.starting_price), bool(existing.flag_url))
        if score > prev_score:
            by_slug[slug] = candidate

    return list(by_slug.values())


def parse_country(html: str, *, slug: str, url: str) -> CountryDetail:
    """Extract the package list from a country / region eSIM page."""
    soup = BeautifulSoup(html, "lxml")

    # Page title h2 is reliably the country / region name.
    name_el = soup.find("h2")
    name = name_el.get_text(strip=True) if name_el else slug.replace("-", " ").title()

    packages: list[Package] = []
    seen: set[str] = set()

    for btn in soup.select('button[aria-label^="Select"]'):
        lbl = (btn.get("aria-label") or "").strip()
        if lbl in seen:
            continue
        m = _PACKAGE_RE.search(lbl)
        if not m:
            continue
        seen.add(lbl)

        unlimited = bool(m.group("unlimited"))
        if unlimited:
            data_text = "Unlimited"
            data_gb: float | None = None
        else:
            size = float(m.group("size"))
            unit = (m.group("unit") or "").upper()
            data_text = f"{m.group('size')} {unit}"
            data_gb = size if unit == "GB" else size / 1024.0

        packages.append(
            Package(
                data=data_text,
                data_gb=data_gb,
                unlimited=unlimited,
                validity_days=int(m.group("validity")),
                currency=m.group("currency"),
                price=float(m.group("price")),
                aria_label=lbl,
            )
        )

    return CountryDetail(name=name, slug=slug, url=url, packages=packages)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def scrape_airalo(
    settings: Settings | None = None,
    *,
    target_name: str = "airalo",
    limit: int | None = None,
    job_id: str | None = None,
    scraper_key: str = SCRAPER_KEY,
) -> tuple[int, PageStats]:
    """Run the full Airalo scrape and persist every country.

    Args:
        settings: project settings (defaults to ``get_settings()``).
        target_name: storage target name (used as the JSONL filename / SQL
            ``target`` column).
        limit: optional cap on the number of countries to fetch -- handy for
            smoke-testing without hitting every link.
        job_id: reuse a job UUID across calls. Defaults to a fresh ``uuid4()``
            so every record produced here shares the same join key.
        scraper_key: tag written to each record + page-stats row.

    Returns:
        Tuple of ``(written_count, session_stats)``. ``session_stats`` carries
        the job ID so downstream consumers can join per-page metrics back to
        this scrape run.
    """
    s = settings or get_settings()
    jid = job_id or str(uuid4())
    session = PageStats(
        target=target_name,
        url=INDEX_URL,
        job_id=jid,
        scraper_key=scraper_key,
    )

    # ---- phase 1: index page -------------------------------------------
    with page_stats(
        target=target_name,
        url=INDEX_URL,
        job_id=jid,
        scraper_key=scraper_key,
    ) as idx_stats:
        log.info("airalo.index.fetching", url=INDEX_URL, job_id=jid)
        index_resp = await fetch_url(INDEX_URL, s)
        record_request()
        set_complexity(html=index_resp.text)

        if s.scraper.save_raw_html:
            save_raw_html_artifact(index_resp.text, s.scraper.raw_html_dir, target_name, INDEX_URL)
        if s.scraper.save_markdown:
            save_markdown_artifact(index_resp.text, s.scraper.markdown_dir, target_name, INDEX_URL)

        with extracting():
            entries = parse_index(index_resp.text)
    session.merge(idx_stats)

    if limit is not None:
        entries = entries[:limit]
    log.info("airalo.index.parsed", countries=len(entries), job_id=jid)

    # ---- phase 2: per-country pages ------------------------------------
    sem = asyncio.Semaphore(s.scraper.concurrency)

    async def _one(entry: CountryEntry) -> tuple[dict[str, Any] | None, PageStats]:
        async with sem:
            with page_stats(
                target=target_name,
                url=entry.url,
                job_id=jid,
                scraper_key=scraper_key,
            ) as ps:
                try:
                    resp = await fetch_url(entry.url, s)
                    record_request()
                    set_complexity(html=resp.text)
                    if s.scraper.save_raw_html:
                        save_raw_html_artifact(
                            resp.text, s.scraper.raw_html_dir, target_name, entry.url
                        )
                    if s.scraper.save_markdown:
                        save_markdown_artifact(
                            resp.text, s.scraper.markdown_dir, target_name, entry.url
                        )
                    with extracting():
                        detail = parse_country(resp.text, slug=entry.slug, url=entry.url)
                except Exception as exc:
                    log.error(
                        "airalo.country.failed",
                        slug=entry.slug,
                        error=str(exc),
                        job_id=jid,
                    )
                    return None, ps

                data = {
                    "name": detail.name,
                    "slug": entry.slug,
                    "flag_url": entry.flag_url,
                    "starting_price": entry.starting_price,
                    "package_count": len(detail.packages),
                    "packages": [asdict(p) for p in detail.packages],
                }
                record = {
                    "job_id": jid,
                    "record_id": ps.record_id,
                    "scraper_key": scraper_key,
                    "url": entry.url,
                    "status": resp.status_code,
                    "data": data,
                    "metadata": {
                        "stats": ps.to_dict(),
                        "artifacts": ps.artifacts.to_dict(),
                    },
                }
                log.info(
                    "airalo.country.done",
                    slug=entry.slug,
                    packages=len(detail.packages),
                    job_id=jid,
                    record_id=ps.record_id,
                )
                return record, ps

    pairs = await asyncio.gather(*(_one(e) for e in entries))
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
        "airalo.done",
        job_id=jid,
        scraper_key=scraper_key,
        countries=len(entries),
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
