"""Tests for airalo.stats: counters, scopes, and complexity."""

from __future__ import annotations

import asyncio
import time

import pytest

from airalo.stats import (
    PageStats,
    compute_page_complexity,
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

# ---------------------------------------------------------------------------
# PageStats dataclass
# ---------------------------------------------------------------------------


def test_page_stats_defaults() -> None:
    s = PageStats(target="t", url="u")
    assert s.page_requests == 0
    assert s.clicks == 0
    assert s.screenshots == 0
    assert s.videos == 0
    assert s.llm_calls == 0
    assert s.llm_total_tokens == 0
    assert s.extraction_count == 0
    assert s.extraction_success_rate is None
    assert s.page_complexity == 0.0


def test_record_helpers_increment_counters() -> None:
    s = PageStats(target="t", url="u")
    s.record_request(2)
    s.record_click()
    s.record_screenshot(3)
    s.record_video()
    s.record_llm(input_tokens=10, output_tokens=20)
    s.record_extraction(success=True)
    s.record_extraction(success=False)

    assert s.page_requests == 2
    assert s.clicks == 1
    assert s.screenshots == 3
    assert s.videos == 1
    assert s.llm_calls == 1
    assert s.llm_input_tokens == 10
    assert s.llm_output_tokens == 20
    assert s.llm_total_tokens == 30
    assert s.extractions_succeeded == 1
    assert s.extractions_failed == 1
    assert s.extraction_count == 2
    assert s.extraction_success_rate == 0.5


def test_set_complexity_keeps_max() -> None:
    s = PageStats()
    s.set_complexity(40.0)
    s.set_complexity(10.0)
    s.set_complexity(75.5)
    assert s.page_complexity == 75.5


def test_merge_is_additive_and_complexity_is_max() -> None:
    a = PageStats(target="x")
    a.record_request(2)
    a.record_llm(input_tokens=5, output_tokens=5)
    a.set_complexity(20.0)

    b = PageStats(target="y")
    b.record_request(3)
    b.record_llm(input_tokens=10, output_tokens=10)
    b.set_complexity(80.0)

    a.merge(b)
    assert a.page_requests == 5
    assert a.llm_calls == 2
    assert a.llm_total_tokens == 30
    assert a.page_complexity == 80.0


def test_to_dict_round_trip_shape() -> None:
    s = PageStats(target="t", url="u").finalize()
    payload = s.to_dict()
    expected = {
        "job_id",
        "record_id",
        "scraper_key",
        "target",
        "url",
        "page_requests",
        "clicks",
        "screenshots",
        "videos",
        "llm_calls",
        "llm_input_tokens",
        "llm_output_tokens",
        "llm_total_tokens",
        "extractions_succeeded",
        "extractions_failed",
        "extraction_count",
        "extraction_success_rate",
        "extraction_started_at",
        "extraction_finished_at",
        "extraction_time_ms",
        "page_complexity",
        "start_timestamp",
        "end_timestamp",
        "duration_ms",
    }
    assert expected.issubset(payload.keys())


# ---------------------------------------------------------------------------
# Identifiers + scraper_key
# ---------------------------------------------------------------------------


def test_default_record_id_is_unique_uuid() -> None:
    a = PageStats()
    b = PageStats()
    assert a.record_id != b.record_id
    # Should be a UUID4 string (36 chars including 4 dashes).
    assert len(a.record_id) == 36 and a.record_id.count("-") == 4


def test_page_stats_scope_propagates_job_and_scraper_key() -> None:
    with page_stats(target="t", url="u", job_id="job-1", scraper_key="airalo") as s:
        assert s.job_id == "job-1"
        assert s.scraper_key == "airalo"
        assert s.record_id  # auto-generated UUID
    d = s.to_dict()
    assert d["job_id"] == "job-1"
    assert d["scraper_key"] == "airalo"
    assert d["record_id"] == s.record_id


def test_nested_scope_inherits_job_id_from_parent() -> None:
    with (
        page_stats(target="outer", url="o", job_id="job-X") as outer,
        page_stats(target="inner", url="i") as inner,
    ):
        assert inner.job_id == "job-X"  # inherited
        assert inner.record_id != outer.record_id


# ---------------------------------------------------------------------------
# Extraction timing
# ---------------------------------------------------------------------------


def test_extracting_context_records_success_and_time() -> None:
    with page_stats(target="t", url="u") as s, extracting():
        time.sleep(0.02)
    assert s.extractions_succeeded == 1
    assert s.extractions_failed == 0
    assert s.extraction_time_ms >= 10
    assert s.extraction_started_at is not None
    assert s.extraction_finished_at is not None


def test_extracting_context_records_failure_and_reraises() -> None:
    with (
        page_stats(target="t", url="u") as s,
        pytest.raises(RuntimeError, match="boom"),
        extracting(),
    ):
        raise RuntimeError("boom")
    assert s.extractions_succeeded == 0
    assert s.extractions_failed == 1
    assert s.extraction_time_ms >= 0  # cursor was closed


def test_multiple_extractions_are_cumulative() -> None:
    with page_stats(target="t", url="u") as s:
        for _ in range(3):
            with extracting():
                time.sleep(0.005)
    assert s.extractions_succeeded == 3
    assert s.extraction_time_ms >= 10  # ~3 * 5ms minus jitter


def test_finalize_closes_dangling_extraction_cursor() -> None:
    with page_stats(target="t", url="u") as s:
        s.mark_extraction_start()
        # forget to call mark_extraction_end
    assert s._extraction_cursor is None
    assert s.extraction_time_ms >= 0
    assert s.extraction_finished_at is not None


# ---------------------------------------------------------------------------
# page_stats() context manager + ContextVar
# ---------------------------------------------------------------------------


def test_module_recorders_no_op_outside_scope() -> None:
    assert get_current_stats() is None
    record_request(5)
    record_click(5)
    record_screenshot(5)
    record_video(5)
    record_llm_call(input_tokens=100, output_tokens=100)
    record_extraction(success=True)
    set_complexity(99.0)
    assert get_current_stats() is None


def test_module_recorders_inside_scope() -> None:
    with page_stats(target="t", url="u") as s:
        assert get_current_stats() is s

        record_request(3)
        record_click(2)
        record_screenshot()
        record_video()
        record_llm_call(input_tokens=11, output_tokens=22)
        record_extraction(success=True)
        record_extraction(success=False)
        set_complexity(42.0)

    assert s.page_requests == 3
    assert s.clicks == 2
    assert s.screenshots == 1
    assert s.videos == 1
    assert s.llm_calls == 1
    assert s.llm_input_tokens == 11
    assert s.llm_output_tokens == 22
    assert s.extractions_succeeded == 1
    assert s.extractions_failed == 1
    assert s.page_complexity == 42.0
    assert s.end_timestamp is not None


def test_scope_is_restored_on_exit() -> None:
    with page_stats(target="outer") as outer:
        assert get_current_stats() is outer
        with page_stats(target="inner") as inner:
            assert get_current_stats() is inner
        assert get_current_stats() is outer
    assert get_current_stats() is None


def test_concurrent_asyncio_tasks_get_isolated_stats() -> None:
    async def worker(label: str, n: int) -> PageStats:
        with page_stats(target=label) as s:
            for _ in range(n):
                record_request()
                await asyncio.sleep(0)  # yield to other tasks
            return s

    async def driver() -> tuple[PageStats, PageStats]:
        a, b = await asyncio.gather(worker("a", 3), worker("b", 7))
        return a, b

    a, b = asyncio.run(driver())
    assert a.page_requests == 3
    assert b.page_requests == 7


# ---------------------------------------------------------------------------
# compute_page_complexity
# ---------------------------------------------------------------------------


def test_complexity_empty_string_is_zero() -> None:
    assert compute_page_complexity("") == 0.0


def test_complexity_simple_html_is_low() -> None:
    html = "<html><body><p>hello world</p></body></html>"
    score = compute_page_complexity(html)
    assert 0.0 <= score < 25.0


def test_complexity_heavy_html_is_higher() -> None:
    body = (
        "<html><body>"
        + "".join(f"<div><span>{i}</span></div>" for i in range(2000))
        + "".join(f"<script>x = {i};</script>" for i in range(40))
        + "<form>"
        + "".join(f"<input name='i{i}'>" for i in range(30))
        + "</form>"
        + "<iframe src='a'></iframe><iframe src='b'></iframe>"
        + "</body></html>"
    )
    score = compute_page_complexity(body)
    assert score > 35.0


def test_complexity_saturates_at_100() -> None:
    huge = "<div>" * 50_000 + "x" * 2_000_000 + "</div>" * 50_000
    score = compute_page_complexity(huge)
    assert score <= 100.0


def test_set_complexity_from_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """`set_complexity(html=...)` should compute and store the score."""
    with page_stats() as s:
        set_complexity(html="<html><body><p>x</p></body></html>")
    assert s.page_complexity >= 0.0
