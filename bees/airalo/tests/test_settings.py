"""Smoke tests for the settings layer."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from airalo.settings import Settings


def test_defaults_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CONFIG_FILE", raising=False)
    s = Settings()
    assert s.app_name == "Airalo Scraper"
    assert s.scraper.max_retries == 3


def test_yaml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            scraper:
              max_retries: 7
              user_agent: "test-bot/1.0"
            targets:
              - name: foo
                start_urls: ["https://example.org/"]
            """
        ).strip()
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONFIG_FILE", str(cfg))

    s = Settings()
    assert s.scraper.max_retries == 7
    assert s.scraper.user_agent == "test-bot/1.0"
    assert s.get_target("foo") is not None
    assert s.get_target("missing") is None


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scraper:\n  max_retries: 7\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CONFIG_FILE", str(cfg))
    monkeypatch.setenv("SCRAPER__MAX_RETRIES", "11")

    s = Settings()
    assert s.scraper.max_retries == 11
