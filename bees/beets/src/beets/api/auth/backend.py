"""Authentication backends.

Two transports are registered against a single JWT strategy so the same
identity works in both the dashboard and API-client contexts:

* ``cookie`` — ``HttpOnly`` cookie set on login. The Jinja2 UI relies on it.
* ``bearer`` — ``Authorization: Bearer <jwt>``. Suited for scripts / Swagger UI.

Both backends issue the same JWT (signed with ``api.jwt_secret``), so a token
obtained from one can be presented to the other.
"""

from __future__ import annotations

from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)

from beets.settings import get_settings


def _build_cookie_transport() -> CookieTransport:
    s = get_settings().api
    return CookieTransport(
        cookie_name=s.cookie_name,
        cookie_max_age=s.jwt_lifetime_seconds,
        cookie_secure=s.cookie_secure,
        cookie_httponly=True,
        cookie_samesite=s.cookie_samesite,
    )


def get_jwt_strategy() -> JWTStrategy:
    s = get_settings().api
    return JWTStrategy(secret=s.jwt_secret, lifetime_seconds=s.jwt_lifetime_seconds)


cookie_transport = _build_cookie_transport()
bearer_transport = BearerTransport(tokenUrl="auth/bearer/login")

cookie_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

bearer_backend = AuthenticationBackend(
    name="bearer",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
