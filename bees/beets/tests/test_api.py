"""End-to-end tests for the auth + fetch API surface.

Spins up the FastAPI app against a temporary SQLite database, registers a
user, logs in (cookie + bearer), seeds two ``ScrapedItemORM`` rows + one
``PageArtifactORM`` row, and exercises:

* ``/auth/register`` / ``/auth/cookie/login`` / ``/auth/bearer/login`` / ``/users/me``
* ``/api/fetch/records`` and ``/api/fetch/records/{id}``
* ``/api/fetch/jobs``, ``/jobs/{id}``, ``/jobs/{id}/records``
* ``/api/fetch/artifacts``, ``/artifacts/{id}/file``
* ``/api/fetch/stats/*``
* ``/ui/login`` (anon) and ``/ui/dashboard`` (authenticated cookie).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("httpx")
pytest.importorskip("fastapi_users")

from httpx import ASGITransport, AsyncClient  # noqa: I001


JOB_ID = "11111111-2222-3333-4444-555555555555"
REC_A = "aaaa1111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REC_B = "bbbb2222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def configure_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("STORAGE__DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("STORAGE__BACKEND", "sql")
    monkeypatch.setenv("STORAGE__OUTPUT_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("API__JWT_SECRET", "test-secret-please-change-to-32-bytes-min")
    monkeypatch.setenv("API__JWT_LIFETIME_SECONDS", "3600")
    monkeypatch.setenv("API__COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("API__ALLOW_REGISTRATION", "true")
    monkeypatch.setenv("API__ENABLE_UI", "true")

    from beets.api import database as api_db
    from beets.settings import get_settings

    get_settings.cache_clear()
    # Reset module-level engine/sessionmaker so each test gets a fresh DB.
    api_db._engine = None
    api_db._sessionmaker = None
    return db_path


async def _seed_records(db_path: Path) -> None:
    from beets.api.database import get_session_maker, init_db
    from beets.storage.models import PageArtifactORM, ScrapedItemORM

    # Use init_db so the User table is registered alongside scraped_items.
    await init_db()

    sm = get_session_maker()
    async with sm() as session:
        session.add_all(
            [
                ScrapedItemORM(
                    job_id=JOB_ID,
                    record_id=REC_A,
                    scraper_key="httpx",
                    target="example",
                    url="https://example.com/a",
                    status=200,
                    data={"title": "A"},
                    metadata_={"stats": {"page_complexity_score": 0.2, "page_requests": 1}},
                    scraped_at=datetime.fromisoformat("2026-05-14T10:00:00+00:00"),
                ),
                ScrapedItemORM(
                    job_id=JOB_ID,
                    record_id=REC_B,
                    scraper_key="playwright",
                    target="example",
                    url="https://example.com/b",
                    status=500,
                    data={"title": "B"},
                    metadata_={"stats": {"page_complexity_score": 0.9, "page_requests": 7}},
                    scraped_at=datetime.fromisoformat("2026-05-14T11:00:00+00:00"),
                ),
            ]
        )
        artifact_path = db_path.parent / "screenshot.png"
        artifact_path.write_bytes(b"PNGFAKE")
        session.add(
            PageArtifactORM(
                record_id=REC_B,
                job_id=JOB_ID,
                target="example",
                kind="screenshot",
                path=str(artifact_path),
                media_type="image/png",
                size_bytes=artifact_path.stat().st_size,
                width=1280,
                height=720,
            )
        )
        await session.commit()


async def _logged_in_client(client: AsyncClient) -> dict[str, str]:
    """Register + cookie-login a user. Return its bearer Authorization header."""
    resp = await client.post(
        "/auth/register",
        json={"email": "tester@example.com", "password": "supersecret"},
    )
    assert resp.status_code in (200, 201, 400), resp.text  # 400 if pre-existing

    resp = await client.post(
        "/auth/cookie/login",
        data={"username": "tester@example.com", "password": "supersecret"},
    )
    assert resp.status_code in (200, 204), resp.text

    resp = await client.post(
        "/auth/bearer/login",
        data={"username": "tester@example.com", "password": "supersecret"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _build_client(db_path: Path) -> AsyncClient:
    from beets.api.app import create_app

    await _seed_records(db_path)
    app = create_app()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_register_login_and_users_me(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        bearer = await _logged_in_client(client)
        me = await client.get("/users/me", headers=bearer)
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == "tester@example.com"
        assert "id" in body


async def test_fetch_endpoints_require_auth(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        for path in ("/api/fetch/records", "/api/fetch/jobs", "/api/fetch/stats/summary"):
            r = await client.get(path)
            assert r.status_code == 401, f"{path} -> {r.status_code}"


async def test_fetch_records_and_filters(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)

        r = await client.get("/api/fetch/records")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert {it["record_id"] for it in body["items"]} == {REC_A, REC_B}

        r = await client.get("/api/fetch/records", params={"scraper_key": "playwright"})
        body = r.json()
        assert body["total"] == 1
        assert body["items"][0]["record_id"] == REC_B

        r = await client.get(f"/api/fetch/records/{REC_A}")
        assert r.status_code == 200
        assert r.json()["url"] == "https://example.com/a"
        assert r.json()["data"]["title"] == "A"

        r = await client.get("/api/fetch/records/does-not-exist")
        assert r.status_code == 404


async def test_jobs_aggregation(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)

        r = await client.get("/api/fetch/jobs")
        assert r.status_code == 200
        jobs = r.json()
        assert len(jobs) == 1
        j = jobs[0]
        assert j["job_id"] == JOB_ID
        assert j["record_count"] == 2
        assert set(j["scraper_keys"]) == {"httpx", "playwright"}
        assert j["success_count"] == 1
        assert j["failure_count"] == 1

        r = await client.get(f"/api/fetch/jobs/{JOB_ID}")
        body = r.json()
        assert body["artifact_count"] == 1
        assert body["artifacts_by_kind"] == {"screenshot": 1}

        r = await client.get(f"/api/fetch/jobs/{JOB_ID}/records")
        assert r.json()["total"] == 2


async def test_artifacts_listing_and_download(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)

        r = await client.get("/api/fetch/artifacts")
        body = r.json()
        assert body["total"] == 1
        artifact = body["items"][0]
        assert artifact["kind"] == "screenshot"
        assert artifact["width"] == 1280

        r = await client.get(f"/api/fetch/artifacts/{artifact['id']}/file")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/png")
        assert r.content == b"PNGFAKE"


async def test_stats_endpoints(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)

        r = await client.get("/api/fetch/stats/summary")
        body = r.json()
        assert body["records"] == 2
        assert body["jobs"] == 1
        assert body["artifacts"] == 1
        assert body["success_records"] == 1
        assert body["failure_records"] == 1

        r = await client.get("/api/fetch/stats/by-target")
        assert any(row["key"] == "example" and row["count"] == 2 for row in r.json())

        r = await client.get("/api/fetch/stats/by-scraper")
        keys = {row["key"] for row in r.json()}
        assert keys == {"httpx", "playwright"}

        r = await client.get("/api/fetch/stats/by-status")
        statuses = {row["status"]: row["count"] for row in r.json()}
        assert statuses == {200: 1, 500: 1}

        r = await client.get("/api/fetch/stats/by-artifact-kind")
        assert r.json() == [{"key": "screenshot", "count": 1}]

        r = await client.get("/api/fetch/stats/complexity", params={"bins": 5})
        buckets = r.json()
        assert sum(b["count"] for b in buckets) == 2


async def test_ui_login_page_renders_without_auth(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        r = await client.get("/ui/login")
        assert r.status_code == 200
        assert "sign in" in r.text.lower()

        # The dashboard redirects to /ui/login when no cookie is present.
        r = await client.get("/ui/dashboard")
        assert r.status_code in (302, 303, 307)
        assert "/ui/login" in r.headers["location"]


async def test_ui_dashboard_renders_when_authenticated(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)
        r = await client.get("/ui/dashboard")
        assert r.status_code == 200
        body = r.text
        assert "Dashboard" in body
        assert "tester@example.com" in body


async def test_ui_record_detail_shows_data_and_metadata(configure_settings: Path) -> None:
    db_path = configure_settings
    async with await _build_client(db_path) as client:
        await _logged_in_client(client)
        r = await client.get(f"/ui/records/{REC_A}")
        assert r.status_code == 200
        body = r.text
        assert 'id="data"' in body
        assert 'id="metadata"' in body
        assert "title" in body and "A" in body
        assert "page_complexity_score" in body
