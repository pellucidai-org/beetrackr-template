"""Application settings.

Settings are layered from (lowest -> highest precedence):

    1. Defaults defined on the pydantic models below.
    2. ``config.yaml`` (or JSON) pointed to by ``CONFIG_FILE`` env var.
    3. Environment variables (and ``.env`` file).
    4. Constructor kwargs at runtime.

Nested keys use the ``__`` delimiter:

    SCRAPER__USER_AGENT="my-bot/1.0"      # -> settings.scraper.user_agent
    API__PORT=9000                        # -> settings.api.port
Usage:

    from airalo.settings import get_settings
    settings = get_settings()
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------


class ScraperConfig(BaseModel):
    """Generic scraper knobs shared by httpx / bs4 / scrapy / playwright."""

    user_agent: str = "Airalo Scraper/0.1 (+https://example.com)"
    request_timeout: float = 30.0
    max_retries: int = 3
    retry_backoff: float = 1.5
    concurrency: int = 8
    respect_robots_txt: bool = True
    proxy: str | None = None
    default_headers: dict[str, str] = Field(default_factory=dict)

    # Persist the unparsed HTML of every fetched page (useful for debugging /
    # offline re-parsing). Saved as ``<raw_html_dir>/<target>/<slug>.html``.
    save_raw_html: bool = False
    raw_html_dir: Path = Path("./data/html")

    # Convert fetched HTML to Markdown via markdownify and persist a copy.
    # Useful as LLM-friendly input. Saved as
    # ``<markdown_dir>/<target>/<slug>.md``.
    save_markdown: bool = False
    markdown_dir: Path = Path("./data/markdown")


class PlaywrightConfig(BaseModel):
    headless: bool = True
    browser: Literal["chromium", "firefox", "webkit"] = "chromium"
    navigation_timeout_ms: int = 30_000
    viewport: dict[str, int] = Field(default_factory=lambda: {"width": 1366, "height": 768})
    block_resource_types: list[str] = Field(default_factory=list)

    # Retry policy for browser launch (network/binary flakiness).
    launch_max_retries: int = 3
    launch_retry_backoff: float = 2.0

    # Record one .webm per page navigation.
    record_video: bool = False
    record_video_dir: Path = Path("./data/videos")
    record_video_size: dict[str, int] = Field(
        default_factory=lambda: {"width": 1280, "height": 720}
    )

    # Capture a screenshot after every successful navigation.
    screenshot: bool = False
    screenshot_dir: Path = Path("./data/screenshots")
    screenshot_full_page: bool = True
    screenshot_format: Literal["png", "jpeg"] = "png"


class ScrapyAutoThrottle(BaseModel):
    enabled: bool = True
    start_delay: float = 1.0
    max_delay: float = 10.0
    target_concurrency: float = 4.0


class ScrapyPlaywright(BaseModel):
    enabled: bool = True
    default_navigation_timeout: int = 30_000


class ScrapyConfig(BaseModel):
    concurrent_requests: int = 16
    concurrent_requests_per_domain: int = 8
    download_delay: float = 0.5
    download_timeout: int = 30
    autothrottle: ScrapyAutoThrottle = Field(default_factory=ScrapyAutoThrottle)
    playwright: ScrapyPlaywright = Field(default_factory=ScrapyPlaywright)


class ApiConfig(BaseModel):
    """FastAPI server + auth + UI configuration."""

    # ---- server ----------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False

    # Legacy header-based key still used by the /scrape route to authorise
    # ad-hoc fetch requests. Independent from fastapi-users auth below.
    api_key: str = "change-me"

    # ---- database --------------------------------------------------------
    # The API persists users + reads scraped_items / page_artifacts from the
    # same SQLAlchemy database. Defaults to ``storage.database_url`` when
    # unset so a unified Postgres / SQLite store "just works".
    database_url: str | None = None

    # ---- fastapi-users auth ---------------------------------------------
    jwt_secret: str = "change-me-in-production"
    jwt_lifetime_seconds: int = 3600
    cookie_name: str = "airalo_auth"
    cookie_secure: bool = False
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    allow_registration: bool = True
    verify_users: bool = False

    # ---- UI / templates --------------------------------------------------
    enable_ui: bool = True
    ui_page_size: int = 25
    ui_title: str = "Airalo Scraper dashboard"


class StorageConfig(BaseModel):
    """Where scraped items are persisted.

    ``backend`` selects the persistence implementation:

    * ``jsonl`` - write one JSON object per line to ``<output_dir>/<target>.jsonl``
      (default; portable, zero-dependency).
    * ``sql`` - persist into a relational DB via SQLAlchemy 2.0 async.
      Switch backends without code changes — the ``database_url`` decides
      whether you talk to SQLite, PostgreSQL or Supabase (PostgreSQL).
    * ``mongo``, ``kafka`` - placeholders, not yet implemented.

    Example URLs::

        sqlite+aiosqlite:///./data/scraper.db
        postgresql+asyncpg://user:pass@host:5432/scraper
        postgresql+asyncpg://postgres:<pwd>@db.<ref>.supabase.co:5432/postgres
    """

    backend: Literal["jsonl", "sql", "mongo", "kafka"] = "jsonl"
    output_dir: Path = Path("./data")
    format: Literal["jsonl", "csv", "parquet"] = "jsonl"

    # ---- SQL (SQLAlchemy) -------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./data/scraper.db"
    sql_table: str = "scraped_items"
    sql_echo: bool = False
    sql_pool_size: int = 5
    sql_create_tables: bool = True  # auto-run create_all() at startup

    # ---- Mongo (placeholder) ---------------------------------------------
    mongo_url: str | None = None
    mongo_database: str = "scraper"
    mongo_collection: str = "scraped_items"

    # ---- Kafka (placeholder) ---------------------------------------------
    kafka_bootstrap_servers: str | None = None
    kafka_topic: str = "scraped_items"


class TargetPagination(BaseModel):
    enabled: bool = False
    next_selector: str | None = None
    max_pages: int = 1


class TargetConfig(BaseModel):
    name: str
    description: str = ""
    start_urls: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    use_playwright: bool = False
    selectors: dict[str, str] = Field(default_factory=dict)
    pagination: TargetPagination = Field(default_factory=TargetPagination)


# ---------------------------------------------------------------------------
# YAML / JSON config-file source
# ---------------------------------------------------------------------------


class FileConfigSettingsSource(PydanticBaseSettingsSource):
    """Loads structured config from a YAML or JSON file.

    The file path is read from the ``CONFIG_FILE`` environment variable (or the
    ``config_file`` attribute on the model). Missing files are tolerated so the
    app can still run from env vars alone.
    """

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        import os

        path = os.getenv("CONFIG_FILE", "config.yaml")
        self._path = Path(path)
        self._data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        text = self._path.read_text(encoding="utf-8")
        if self._path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(text) or {}
        elif self._path.suffix.lower() == ".json":
            data = json.loads(text) if text.strip() else {}
        else:
            raise ValueError(
                f"Unsupported config file extension: {self._path.suffix!r}. "
                "Use .yaml, .yml or .json."
            )
        if not isinstance(data, dict):
            raise ValueError(f"{self._path} must contain a mapping at the top level.")
        return data

    def get_field_value(self, field: Any, field_name: str) -> tuple[Any, str, bool]:
        if field_name in self._data:
            return self._data[field_name], field_name, False
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return self._data


# ---------------------------------------------------------------------------
# Top-level Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # --- core ---
    app_name: str = "Airalo Scraper"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    config_file: Path = Path("config.yaml")

    # --- nested groups ---
    scraper: ScraperConfig = Field(default_factory=ScraperConfig)
    playwright: PlaywrightConfig = Field(default_factory=PlaywrightConfig)
    scrapy: ScrapyConfig = Field(default_factory=ScrapyConfig)
    api: ApiConfig = Field(default_factory=ApiConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    targets: list[TargetConfig] = Field(default_factory=list)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, v: Any) -> Any:
        return v.upper() if isinstance(v, str) else v

    # ---- precedence: init > env/.env > YAML/JSON config file > defaults ----
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            FileConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    # ---- helpers ----
    def get_target(self, name: str) -> TargetConfig | None:
        return next((t for t in self.targets if t.name == name), None)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
