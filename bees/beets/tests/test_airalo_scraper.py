"""Offline tests for the Airalo parsers (use saved HTML fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from beets.scrapers.airalo import parse_country, parse_index

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# -- /all-esim ----------------------------------------------------------------


def test_parse_index_yields_all_country_cards() -> None:
    entries = parse_index(_load("all_esim.html"))
    # The page lists local + regional + global cards (≈ 214).
    assert len(entries) > 150

    # Every entry has the expected shape.
    for e in entries:
        assert e.name
        assert e.slug
        assert e.url.startswith("https://www.airalo.com/")
        assert e.url.endswith("-esim")

    by_slug = {e.slug: e for e in entries}
    assert "japan" in by_slug
    assert by_slug["japan"].name.lower() == "japan"
    assert by_slug["japan"].starting_price  # priced entry preferred
    assert by_slug["japan"].flag_url  # flag image included


def test_parse_index_dedupes_popular_and_grid_entries() -> None:
    entries = parse_index(_load("all_esim.html"))
    slugs = [e.slug for e in entries]
    # After dedup, every slug appears exactly once.
    assert len(slugs) == len(set(slugs))
    # And most entries should carry a starting price (only the few all-purpose
    # regional carousels may not).
    priced = [e for e in entries if e.starting_price]
    assert len(priced) / len(entries) > 0.9


# -- /japan-esim --------------------------------------------------------------


def test_parse_country_extracts_packages() -> None:
    detail = parse_country(
        _load("japan_esim.html"),
        slug="japan",
        url="https://www.airalo.com/japan-esim",
    )
    assert detail.name == "Japan"
    assert detail.slug == "japan"
    assert len(detail.packages) >= 5

    p0 = detail.packages[0]
    assert p0.validity_days > 0
    assert p0.price > 0
    assert p0.currency in {"$", "£", "€"}
    assert "Select" in p0.aria_label


def test_parse_country_normalises_data_to_gb() -> None:
    detail = parse_country(
        _load("japan_esim.html"),
        slug="japan",
        url="https://www.airalo.com/japan-esim",
    )
    # We saw "1 GB", "3 GB", "5 GB", "10 GB", "20 GB" on the live page.
    sizes = {p.data_gb for p in detail.packages if not p.unlimited}
    assert sizes & {1.0, 3.0, 5.0, 10.0, 20.0}


@pytest.mark.parametrize(
    "label,expected_days,expected_price",
    [
        ("Select 1 GB - 3 days for £3.50.", 3, 3.5),
        ("Select 20 GB - 15 days for $18.50.", 15, 18.5),
        ("Select Unlimited - 7 days for €25.00.", 7, 25.0),
    ],
)
def test_package_regex_handles_known_shapes(
    label: str, expected_days: int, expected_price: float
) -> None:
    from beets.scrapers.airalo import _PACKAGE_RE

    m = _PACKAGE_RE.search(label)
    assert m is not None, label
    assert int(m.group("validity")) == expected_days
    assert float(m.group("price")) == expected_price
