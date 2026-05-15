"""Scrape endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, HttpUrl

from beets.scrapers.bs4_parser import extract_links, extract_title
from beets.scrapers.httpx_client import fetch_url
from beets.settings import Settings, get_settings

router = APIRouter(prefix="/scrape", tags=["scrape"])


# ---- auth ---------------------------------------------------------------


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    if settings.api.api_key in {None, ""} or x_api_key != settings.api.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )


# ---- schema -------------------------------------------------------------


class ScrapeRequest(BaseModel):
    url: HttpUrl
    selectors: dict[str, str] | None = None


class ScrapeResponse(BaseModel):
    url: HttpUrl
    status_code: int
    title: str | None
    links: list[str]


# ---- handlers -----------------------------------------------------------


@router.post(
    "/url",
    response_model=ScrapeResponse,
    dependencies=[Depends(require_api_key)],
)
async def scrape_url(payload: ScrapeRequest) -> ScrapeResponse:
    """Fetch a single URL with httpx and parse it with BeautifulSoup."""
    resp = await fetch_url(str(payload.url))
    return ScrapeResponse(
        url=payload.url,
        status_code=resp.status_code,
        title=extract_title(resp.text),
        links=extract_links(resp.text, base_url=str(payload.url)),
    )


@router.get("/targets", dependencies=[Depends(require_api_key)])
async def list_targets(settings: Settings = Depends(get_settings)) -> list[dict]:
    return [t.model_dump() for t in settings.targets]
