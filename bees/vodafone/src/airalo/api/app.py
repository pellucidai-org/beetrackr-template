"""FastAPI application factory.

The app exposes four surfaces:

* ``/scrape`` — ad-hoc URL scraping (legacy header API key).
* ``/auth/*`` + ``/users/*`` — fastapi-users (cookie + bearer JWT).
* ``/api/fetch/*`` — authenticated read API over the SQL store.
* ``/ui/*`` — Jinja2 dashboard (records, jobs, distributions, charts).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from airalo import __version__
from airalo.api.auth import build_auth_router
from airalo.api.database import close_db, init_db
from airalo.api.routes import fetch, health, scrape
from airalo.api.ui import build_ui_router
from airalo.logging import configure_logging, get_logger
from airalo.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    log = get_logger("api")
    await init_db()
    log.info("api.startup", app=settings.app_name, env=settings.environment)
    try:
        yield
    finally:
        await close_db()
        log.info("api.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description="Scraper for airalo.com listings.",
        debug=settings.debug,
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(scrape.router)
    app.include_router(build_auth_router())
    app.include_router(fetch.router)

    if settings.api.enable_ui:
        app.include_router(build_ui_router())

        @app.get("/", include_in_schema=False)
        async def _root() -> RedirectResponse:
            return RedirectResponse(url="/ui/dashboard")

    return app


app = create_app()
