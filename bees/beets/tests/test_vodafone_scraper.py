"""Offline tests for Vodafone Travel parsers."""

from __future__ import annotations

from pathlib import Path

from beets.scrapers.vodafone import (
    parse_destination,
    parse_destinations_index,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_destinations_index_lists_countries() -> None:
    entries = parse_destinations_index(_load("our_destinations_index.html"))
    slugs = {e.slug for e in entries}
    assert slugs == {"italy", "uk", "europe"}


def test_parse_destinations_index_countries_only_filters_regions() -> None:
    entries = parse_destinations_index(_load("our_destinations_index.html"), countries_only=True)
    assert {e.slug for e in entries} == {"italy", "uk"}


def test_parse_destination_extracts_packages_from_json_ld() -> None:
    detail = parse_destination(
        _load("italy_destination.html"),
        slug="italy",
        url="https://travel.vodafone.com/our-destinations/italy",
    )
    assert detail.name == "Italy"
    assert len(detail.packages) == 5
    pids = {p.product_id for p in detail.packages}
    assert "ITA_3GB10Da" in pids
    assert "ITA_UNLGB15Da" in pids

    unlimited = next(p for p in detail.packages if p.unlimited)
    assert unlimited.data == "Unlimited"
    assert unlimited.validity_days == 15
    assert unlimited.currency == "GBP"
    assert unlimited.price > 0

    gb50 = next(p for p in detail.packages if p.product_id == "ITA_50GB30Da")
    assert gb50.data_gb == 50.0
    assert gb50.validity_days == 30
