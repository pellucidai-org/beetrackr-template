"""``PageStats`` dataclass + ContextVar-based current-scope helpers.

Every page-scrape produces a ``PageStats`` instance carrying:

* **Identifiers** that make stats joinable to extracted data and queryable
  for job monitoring:

  - ``job_id``   - same UUID for every page in a single scrape run/CLI call.
  - ``record_id``- unique UUID for this page (1:1 with the persisted record).
  - ``scraper_key`` - tag for the scraper that produced this page
    (e.g. ``"httpx"``, ``"playwright"``, ``"airalo"``).

* **Counters**: ``page_requests``, ``clicks``, ``screenshots``, ``videos``,
  ``llm_calls`` (+ token usage), ``extractions_succeeded`` / ``_failed``.

* **Timing**: ``start_timestamp`` / ``end_timestamp`` / ``duration_ms`` for the
  whole page; ``extraction_started_at`` / ``extraction_finished_at`` /
  ``extraction_time_ms`` for the parse step only (cumulative if the scraper
  extracts more than once per page).

* **Quality**: ``page_complexity`` heuristic score (see
  :func:`compute_page_complexity`).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from beets.artifacts.models import PageArtifacts


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _new_id() -> str:
    return str(uuid4())


@dataclass(slots=True)
class PageStats:
    """Counters + timing for a single page-scrape operation.

    Mutating methods are safe to call from coroutines on the same event loop;
    they are NOT thread-safe (use one PageStats per asyncio task).
    """

    # ---- identity ------------------------------------------------------
    # Same job_id is shared by every page inside one scrape run.
    job_id: str = ""
    # Unique per page; persisted alongside the record for joins.
    record_id: str = field(default_factory=_new_id)
    # Tag for the scraper that produced this record (e.g. "httpx", "airalo").
    scraper_key: str = ""

    target: str = ""
    url: str = ""

    # ---- counters -------------------------------------------------------
    page_requests: int = 0
    clicks: int = 0
    screenshots: int = 0
    videos: int = 0

    llm_calls: int = 0
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0

    extractions_succeeded: int = 0
    extractions_failed: int = 0

    # ---- derived metrics -----------------------------------------------
    # 0 - 100, see :func:`compute_page_complexity` for the heuristic.
    page_complexity: float = 0.0

    # ---- timing --------------------------------------------------------
    start_timestamp: datetime = field(default_factory=_utcnow)
    end_timestamp: datetime | None = None

    extraction_started_at: datetime | None = None
    extraction_finished_at: datetime | None = None
    # Cumulative time across every extraction step inside this scope.
    extraction_time_ms: float = 0.0
    # Internal cursor for the in-progress extraction (private).
    _extraction_cursor: datetime | None = None

    # ---- artifacts -----------------------------------------------------
    # Files produced during this page-scrape (html, markdown, screenshot,
    # video, ...). Mutate via :func:`airalo.artifacts.record_artifact`.
    artifacts: PageArtifacts = field(default_factory=PageArtifacts)

    # =====================================================================
    # mutators
    # =====================================================================

    def record_request(self, n: int = 1) -> None:
        self.page_requests += n

    def record_click(self, n: int = 1) -> None:
        self.clicks += n

    def record_screenshot(self, n: int = 1) -> None:
        self.screenshots += n

    def record_video(self, n: int = 1) -> None:
        self.videos += n

    def record_llm(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.llm_calls += 1
        self.llm_input_tokens += int(input_tokens)
        self.llm_output_tokens += int(output_tokens)

    def record_extraction(self, success: bool = True) -> None:
        if success:
            self.extractions_succeeded += 1
        else:
            self.extractions_failed += 1

    def mark_extraction_start(self) -> None:
        """Start timing an extraction step. Pair with :meth:`mark_extraction_end`."""
        now = _utcnow()
        if self.extraction_started_at is None:
            self.extraction_started_at = now
        self._extraction_cursor = now

    def mark_extraction_end(self) -> None:
        """End the in-progress extraction; adds elapsed time to ``extraction_time_ms``."""
        if self._extraction_cursor is None:
            return
        now = _utcnow()
        elapsed_ms = (now - self._extraction_cursor).total_seconds() * 1000.0
        self.extraction_time_ms += elapsed_ms
        self.extraction_finished_at = now
        self._extraction_cursor = None

    def set_complexity(self, score: float) -> None:
        """Set complexity; keeps the maximum if called more than once."""
        self.page_complexity = max(self.page_complexity, float(score))

    def finalize(self) -> PageStats:
        if self.end_timestamp is None:
            self.end_timestamp = _utcnow()
        # Close a dangling extraction window so the caller always sees a value.
        if self._extraction_cursor is not None:
            self.mark_extraction_end()
        return self

    # =====================================================================
    # aggregation
    # =====================================================================

    def merge(self, other: PageStats) -> None:
        """Additively fold ``other`` into ``self``. Complexity becomes max."""
        self.page_requests += other.page_requests
        self.clicks += other.clicks
        self.screenshots += other.screenshots
        self.videos += other.videos
        self.llm_calls += other.llm_calls
        self.llm_input_tokens += other.llm_input_tokens
        self.llm_output_tokens += other.llm_output_tokens
        self.extractions_succeeded += other.extractions_succeeded
        self.extractions_failed += other.extractions_failed
        self.extraction_time_ms += other.extraction_time_ms
        self.page_complexity = max(self.page_complexity, other.page_complexity)
        self.artifacts.extend(other.artifacts)

    # =====================================================================
    # derived properties
    # =====================================================================

    @property
    def llm_total_tokens(self) -> int:
        return self.llm_input_tokens + self.llm_output_tokens

    @property
    def duration_ms(self) -> float:
        end = self.end_timestamp or _utcnow()
        return (end - self.start_timestamp).total_seconds() * 1000.0

    @property
    def extraction_count(self) -> int:
        return self.extractions_succeeded + self.extractions_failed

    @property
    def extraction_success_rate(self) -> float | None:
        total = self.extraction_count
        return (self.extractions_succeeded / total) if total else None

    # =====================================================================
    # serialization
    # =====================================================================

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "record_id": self.record_id,
            "scraper_key": self.scraper_key,
            "target": self.target,
            "url": self.url,
            "page_requests": self.page_requests,
            "clicks": self.clicks,
            "screenshots": self.screenshots,
            "videos": self.videos,
            "llm_calls": self.llm_calls,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_total_tokens": self.llm_total_tokens,
            "extractions_succeeded": self.extractions_succeeded,
            "extractions_failed": self.extractions_failed,
            "extraction_count": self.extraction_count,
            "extraction_success_rate": self.extraction_success_rate,
            "page_complexity": self.page_complexity,
            "start_timestamp": self.start_timestamp.isoformat(),
            "end_timestamp": (self.end_timestamp or _utcnow()).isoformat(),
            "duration_ms": round(self.duration_ms, 3),
            "extraction_started_at": (
                self.extraction_started_at.isoformat()
                if self.extraction_started_at is not None
                else None
            ),
            "extraction_finished_at": (
                self.extraction_finished_at.isoformat()
                if self.extraction_finished_at is not None
                else None
            ),
            "extraction_time_ms": round(self.extraction_time_ms, 3),
        }


# ===========================================================================
# Current-scope plumbing via ContextVar
# ===========================================================================


_current: ContextVar[PageStats | None] = ContextVar("page_stats_current", default=None)


def get_current_stats() -> PageStats | None:
    """Return the active ``PageStats``, or ``None`` if no scope is open."""
    return _current.get()


@contextmanager
def page_stats(
    *,
    target: str = "",
    url: str = "",
    job_id: str = "",
    scraper_key: str = "",
    record_id: str | None = None,
    stats: PageStats | None = None,
) -> Iterator[PageStats]:
    """Open a PageStats scope.

    While inside the ``with`` block, ``get_current_stats()`` and the
    ``record_*`` helpers in this module operate on the same instance.

    Args:
        target: target name (config.yaml entry).
        url: URL being scraped.
        job_id: shared job UUID. If empty and a parent scope is active, the
            parent's ``job_id`` is inherited automatically.
        scraper_key: tag identifying which scraper produced this page.
        record_id: override the auto-generated per-page UUID (rarely needed).
        stats: provide a pre-built PageStats (overrides every other kwarg).
    """
    if stats is None:
        parent = _current.get()
        if not job_id and parent is not None and parent.job_id:
            job_id = parent.job_id
        stats = PageStats(
            target=target,
            url=url,
            job_id=job_id,
            scraper_key=scraper_key,
            record_id=record_id or _new_id(),
        )
    token = _current.set(stats)
    try:
        yield stats
    finally:
        stats.finalize()
        _current.reset(token)


@contextmanager
def extracting() -> Iterator[None]:
    """Context manager that times an extraction step *and* records its outcome.

    Inside the block:
    * extraction start time is captured;
    * on clean exit ``extractions_succeeded`` is incremented;
    * on exception ``extractions_failed`` is incremented and the exception
      propagates;
    * either way ``extraction_time_ms`` is updated.

    No-ops when no ``page_stats`` scope is active.
    """
    s = _current.get()
    if s is not None:
        s.mark_extraction_start()
    try:
        yield
        if s is not None:
            s.record_extraction(success=True)
    except Exception:
        if s is not None:
            s.record_extraction(success=False)
        raise
    finally:
        if s is not None:
            s.mark_extraction_end()


# ---------------------------------------------------------------------------
# Module-level recorders - safe to call when no scope is open (no-op).
# Use these from library code (HTTP wrappers, LLM clients, ...).
# ---------------------------------------------------------------------------


def record_request(n: int = 1) -> None:
    if (s := _current.get()) is not None:
        s.record_request(n)


def record_click(n: int = 1) -> None:
    if (s := _current.get()) is not None:
        s.record_click(n)


def record_screenshot(n: int = 1) -> None:
    if (s := _current.get()) is not None:
        s.record_screenshot(n)


def record_video(n: int = 1) -> None:
    if (s := _current.get()) is not None:
        s.record_video(n)


def record_llm_call(input_tokens: int = 0, output_tokens: int = 0) -> None:
    if (s := _current.get()) is not None:
        s.record_llm(input_tokens, output_tokens)


def record_extraction(success: bool = True) -> None:
    if (s := _current.get()) is not None:
        s.record_extraction(success)


def set_complexity(score: float | None = None, *, html: str | None = None) -> None:
    """Update ``page_complexity`` either directly or by scoring HTML."""
    if (s := _current.get()) is None:
        return
    if html is not None:
        from beets.stats.complexity import compute_page_complexity

        score = compute_page_complexity(html)
    if score is not None:
        s.set_complexity(score)
