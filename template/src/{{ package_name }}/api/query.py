"""FastAPI query parameter helpers."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Query
from pydantic import BeforeValidator


def _empty_str_int_none(value: Any) -> int | None:
    """Treat blank query values as unset (HTML forms send ``status=``)."""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        return int(stripped)
    if isinstance(value, int):
        return value
    return int(value)


def OptionalIntQuery(*, alias: str | None = None) -> Any:
    """Optional integer :class:`Query` that accepts empty strings."""
    kwargs: dict[str, Any] = {}
    if alias is not None:
        kwargs["alias"] = alias
    return Annotated[int | None, BeforeValidator(_empty_str_int_none), Query(**kwargs)]


StatusCodeQuery = OptionalIntQuery(alias="status")
