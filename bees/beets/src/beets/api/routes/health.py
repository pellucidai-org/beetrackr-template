"""Liveness / readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from beets import __version__
from beets.settings import get_settings

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/info")
async def info() -> dict[str, str]:
    s = get_settings()
    return {
        "app": s.app_name,
        "version": __version__,
        "environment": s.environment,
    }
