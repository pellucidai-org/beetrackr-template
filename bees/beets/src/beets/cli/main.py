"""Typer-based CLI for Beets (Bee Travel eSIM scrapers).

Run ``beets --help`` after installing.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import typer
from rich.console import Console
from rich.table import Table

from beets import __version__
from beets.logging import configure_logging, get_logger
from beets.settings import get_settings
from beets.stats import PageStats

app = typer.Typer(
    name="beets",
    help="Bee Travel eSIM scrapers (Airalo + Vodafone Travel).",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

ScrapeProvider = Literal["airalo", "vodafone"]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]beets[/bold] {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="Show version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Beets CLI."""
    settings = get_settings()
    configure_logging(settings.log_level)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command("config")
def show_config(
    as_json: Annotated[bool, typer.Option("--json", help="Output as JSON.")] = False,
) -> None:
    """Print the merged effective configuration."""
    settings = get_settings()
    if as_json:
        console.print_json(settings.model_dump_json(indent=2))
        return

    table = Table(title="Effective settings", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key, value in settings.model_dump().items():
        table.add_row(key, json.dumps(value, default=str))
    console.print(table)


@app.command("targets")
def list_targets() -> None:
    """List configured scrape targets from config.yaml."""
    settings = get_settings()
    if not settings.targets:
        console.print("[yellow]No targets defined in config.yaml[/yellow]")
        raise typer.Exit()

    table = Table(title="Scrape targets")
    table.add_column("Name", style="cyan")
    table.add_column("Start URLs", style="white")
    table.add_column("Playwright", style="magenta")
    table.add_column("Description")
    for t in settings.targets:
        table.add_row(
            t.name,
            "\n".join(t.start_urls),
            "yes" if t.use_playwright else "no",
            t.description,
        )
    console.print(table)


@app.command("run")
def run(
    target: Annotated[str, typer.Argument(help="Name of target defined in config.yaml")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Override output directory."),
    ] = None,
    job_id: Annotated[
        str | None,
        typer.Option(
            "--job-id",
            help="Reuse a job UUID (defaults to a fresh uuid4 per invocation).",
        ),
    ] = None,
    show_stats: Annotated[
        bool,
        typer.Option("--stats/--no-stats", help="Print session stats table when done."),
    ] = True,
) -> None:
    """Run a scrape target with the appropriate backend."""
    log = get_logger("cli.run")
    settings = get_settings()
    cfg = settings.get_target(target)
    if cfg is None:
        console.print(f"[red]Unknown target:[/red] {target}")
        raise typer.Exit(code=1)

    out_dir = output or settings.storage.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jid = job_id or str(uuid4())
    console.print(
        f"[bold cyan]job[/bold cyan] [magenta]{jid}[/magenta]  target=[green]{cfg.name}[/green]"
    )
    log.info(
        "running.target",
        target=cfg.name,
        job_id=jid,
        urls=cfg.start_urls,
        output=str(out_dir),
    )

    if cfg.use_playwright:
        from beets.scrapers.playwright_runner import run_playwright_target

        written, session = asyncio.run(run_playwright_target(cfg, settings, job_id=jid))
    else:
        from beets.scrapers.httpx_client import run_httpx_target

        written, session = asyncio.run(run_httpx_target(cfg, settings, out_dir, job_id=jid))

    if show_stats:
        _print_session_stats(cfg.name, written, session)


@app.command("scrape")
def scrape_cmd(
    provider: Annotated[
        ScrapeProvider,
        typer.Option(
            "--provider",
            "-p",
            help="Which travel eSIM site to scrape.",
        ),
    ] = "airalo",
    limit: Annotated[
        int | None,
        typer.Option(
            "--limit",
            "-n",
            help="Max pages after the index (smoke tests).",
        ),
    ] = None,
    job_id: Annotated[
        str | None,
        typer.Option(
            "--job-id",
            help="Reuse a job UUID (defaults to a fresh uuid4 for this run).",
        ),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--target",
            help="Storage target name (defaults to the provider name).",
        ),
    ] = None,
    include_regions: Annotated[
        bool,
        typer.Option(
            "--include-regions/--countries-only",
            help="(Vodafone) Also scrape regional hub pages, not only countries.",
        ),
    ] = False,
    show_stats: Annotated[
        bool,
        typer.Option("--stats/--no-stats", help="Print session stats table when done."),
    ] = True,
) -> None:
    """Scrape Airalo or Vodafone Travel eSIM listings.

    * ``beets scrape -p airalo`` — httpx + bs4, ``/all-esim`` + country pages.
    * ``beets scrape -p vodafone`` — Playwright, ``/our-destinations`` + JSON-LD plans.

      For generic config-driven targets, use ``beets run <target>`` instead.
    """
    settings = get_settings()
    storage_target = target or provider
    jid = job_id or str(uuid4())
    log = get_logger("cli.scrape")
    console.print(
        f"[bold cyan]job[/bold cyan] [magenta]{jid}[/magenta]  "
        f"provider=[green]{provider}[/green]  target=[green]{storage_target}[/green]"
        + (f"  [dim]limit={limit}[/dim]" if limit is not None else "")
    )

    if provider == "airalo":
        from beets.scrapers.airalo import scrape_airalo

        log.info("airalo.scrape.starting", job_id=jid, target=storage_target, limit=limit)
        written, session = asyncio.run(
            scrape_airalo(settings, target_name=storage_target, limit=limit, job_id=jid)
        )
    elif provider == "vodafone":
        from beets.scrapers.vodafone import scrape_vodafone

        log.info("vodafone.scrape.starting", job_id=jid, target=storage_target, limit=limit)
        written, session = asyncio.run(
            scrape_vodafone(
                settings,
                target_name=storage_target,
                limit=limit,
                job_id=jid,
                countries_only=not include_regions,
            )
        )
    else:
        console.print(f"[red]Unknown provider:[/red] {provider}")
        raise typer.Exit(code=1)

    if show_stats:
        _print_session_stats(storage_target, written, session)


def _print_session_stats(target: str, written: int, session: PageStats) -> None:
    """Render aggregate per-target counters as a rich table."""
    table = Table(title=f"Session stats - {target}", show_header=False, show_lines=False)
    table.add_column("metric", style="cyan", no_wrap=True)
    table.add_column("value", style="green", justify="right")
    rows: list[tuple[str, str]] = [
        ("job id", session.job_id or "-"),
        ("scraper key", session.scraper_key or "-"),
        ("records written", str(written)),
        ("page requests", str(session.page_requests)),
        ("clicks", str(session.clicks)),
        ("screenshots", str(session.screenshots)),
        ("videos", str(session.videos)),
        ("llm calls", str(session.llm_calls)),
        ("llm input tokens", str(session.llm_input_tokens)),
        ("llm output tokens", str(session.llm_output_tokens)),
        ("llm total tokens", str(session.llm_total_tokens)),
        ("extractions ok", str(session.extractions_succeeded)),
        ("extractions failed", str(session.extractions_failed)),
        (
            "extraction success rate",
            f"{session.extraction_success_rate:.0%}"
            if session.extraction_success_rate is not None
            else "n/a",
        ),
        ("page complexity (max)", f"{session.page_complexity:.1f}/100"),
        ("extraction time", f"{session.extraction_time_ms / 1000:.2f}s"),
        ("duration", f"{session.duration_ms / 1000:.2f}s"),
        ("artifacts", _format_artifacts(session)),
    ]
    for k, v in rows:
        table.add_row(k, v)
    console.print(table)


def _format_artifacts(session: PageStats) -> str:
    if not session.artifacts:
        return "0"
    by_kind: dict[str, int] = {}
    for a in session.artifacts:
        by_kind[a.kind] = by_kind.get(a.kind, 0) + 1
    breakdown = ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items()))
    total_kb = session.artifacts.total_bytes / 1024.0
    return f"{len(session.artifacts)} ({breakdown}, {total_kb:.1f} KB)"


@app.command("crawl")
def crawl(
    spider: Annotated[str, typer.Argument(help="Scrapy spider name.")] = "example",
) -> None:
    """Run a Scrapy spider (uses scrapy-playwright when configured)."""
    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    process = CrawlerProcess(get_project_settings())
    process.crawl(spider)
    process.start()


@app.command("serve")
def serve(
    host: Annotated[str | None, typer.Option(help="Override API host.")] = None,
    port: Annotated[int | None, typer.Option(help="Override API port.")] = None,
    reload: Annotated[
        bool, typer.Option("--reload/--no-reload", help="Enable autoreload.")
    ] = False,
) -> None:
    """Run the FastAPI service with uvicorn."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "beets.api.app:app",
        host=host or settings.api.host,
        port=port or settings.api.port,
        reload=reload or settings.api.reload,
    )


# ---------------------------------------------------------------------------
# db: bootstrap / wipe the SQL schema
# ---------------------------------------------------------------------------

db_app = typer.Typer(help="SQL storage management.", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Create tables for the SQL storage backend."""
    settings = get_settings()
    if settings.storage.backend != "sql":
        console.print(
            f"[yellow]storage.backend is {settings.storage.backend!r}, "
            "not 'sql' - nothing to do.[/yellow]"
        )
        raise typer.Exit()

    async def _run() -> None:
        from beets.storage.sql import SQLAlchemyBackend

        backend = SQLAlchemyBackend(settings)
        await backend.init()
        await backend.close()

    asyncio.run(_run())
    console.print("[green]SQL schema ready.[/green]")


@db_app.command("drop")
def db_drop(
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Drop all SQL tables. Destructive."""
    settings = get_settings()
    if settings.storage.backend != "sql":
        console.print(
            f"[yellow]storage.backend is {settings.storage.backend!r}, "
            "not 'sql' - nothing to do.[/yellow]"
        )
        raise typer.Exit()

    if not yes and not typer.confirm("Drop all SQL tables?"):
        raise typer.Abort()

    async def _run() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        from beets.storage.models import Base

        engine = create_async_engine(settings.storage.database_url)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(_run())
    console.print("[red]SQL schema dropped.[/red]")


if __name__ == "__main__":
    app()
