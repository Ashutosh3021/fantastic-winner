"""Row access for tables whose primary key is not ``id``.

PyroCore's row endpoints assume an ``id`` column. ``user_preferences`` is keyed
by ``user_id`` and ``cm_login_codes`` by ``code_hash``, so a row-id GET/PATCH on
them answered 500. That aborted the very first GitHub sign-in: the profile row
was created, then creating its preferences failed and the callback returned 503.
A retry only "worked" because the user already existed and the preferences step
was skipped.
"""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from app.api.routers.auth import _public_base_url
from app.core.config import AuthConfig
from app.repositories.store import LoginCodeRepository, PreferencesRepository


class _Batch:
    def __init__(self, changes: int) -> None:
        self._changes = changes

    def changes(self, index: int = 0) -> int:
        return self._changes


class RowGateway:
    """Serves filter reads and fails loudly if a row-id endpoint is used."""

    def __init__(self, rows: list[dict[str, Any]] | None = None, *, changes: int = 1) -> None:
        self.rows = rows or []
        self.changes_value = changes
        self.filters: list[tuple[str | None, str | None]] = []
        self.inserts: list[dict[str, Any]] = []
        self.statements: list[str] = []

    async def list_rows(
        self,
        table: str,
        *,
        limit: int = 50,
        offset: int = 0,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> list[dict[str, Any]]:
        self.filters.append((filter_column, filter_value))
        return list(self.rows)

    async def insert_row(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        self.inserts.append(data)
        return data

    async def get_row(self, table: str, row_id: str) -> dict[str, Any] | None:
        raise AssertionError(f"row-id GET must not be used by {table}")

    async def update_row(
        self, table: str, row_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        raise AssertionError(f"row-id PATCH must not be used by {table}")

    async def execute(self, statements: list[str]) -> _Batch:
        self.statements.extend(statements)
        return _Batch(self.changes_value)


async def test_preferences_ensure_creates_the_first_row_by_filter() -> None:
    gw = RowGateway(rows=[])
    repo = PreferencesRepository(gw)  # type: ignore[arg-type]

    await repo.ensure("user-1")

    assert gw.filters == [("user_id", "user-1")]
    assert len(gw.inserts) == 1
    assert gw.inserts[0]["user_id"] == "user-1"
    assert gw.inserts[0]["prefs_version"] == 1


async def test_preferences_for_user_reads_existing_row_by_filter() -> None:
    gw = RowGateway(rows=[{"user_id": "user-1", "prefs_version": 4, "language": "en"}])
    repo = PreferencesRepository(gw)  # type: ignore[arg-type]

    row = await repo.for_user("user-1")

    assert row["prefs_version"] == 4
    assert gw.inserts == []


async def test_preferences_patch_updates_by_user_id_not_row_id() -> None:
    gw = RowGateway(rows=[{"user_id": "user-1", "prefs_version": 2, "language": "en"}])
    repo = PreferencesRepository(gw)  # type: ignore[arg-type]

    merged = await repo.patch("user-1", {"theme": "dark", "timezone": None})

    assert merged["theme"] == "dark"
    assert merged["prefs_version"] == 3
    assert "timezone" not in merged
    assert len(gw.statements) == 1
    assert gw.statements[0].startswith("UPDATE user_preferences SET ")
    assert "WHERE user_id = 'user-1'" in gw.statements[0]
    assert "user_id = " not in gw.statements[0].split(" SET ", 1)[1].split(" WHERE ", 1)[0]


async def test_login_code_consume_marks_it_used_with_one_conditional_update() -> None:
    raw = "code-abc"
    gw = RowGateway(
        rows=[
            {
                "code_hash": LoginCodeRepository.hash_code(raw),
                "user_id": "user-1",
                "consumed_at": None,
                "expires_at": "2999-01-01T00:00:00.000Z",
            }
        ]
    )
    repo = LoginCodeRepository(gw)  # type: ignore[arg-type]

    row = await repo.consume(raw)

    assert row is not None and row["user_id"] == "user-1"
    assert len(gw.statements) == 1
    assert gw.statements[0].startswith("UPDATE cm_login_codes SET consumed_at = ")
    assert "WHERE code_hash = " in gw.statements[0]
    assert "AND consumed_at IS NULL" in gw.statements[0]


async def test_login_code_consume_survives_a_race_without_a_second_use() -> None:
    raw = "code-abc"
    gw = RowGateway(
        rows=[
            {
                "code_hash": LoginCodeRepository.hash_code(raw),
                "user_id": "user-1",
                "consumed_at": None,
                "expires_at": "2999-01-01T00:00:00.000Z",
            }
        ],
        changes=0,
    )
    repo = LoginCodeRepository(gw)  # type: ignore[arg-type]

    assert await repo.consume(raw) is None


async def test_login_code_consume_skips_used_and_expired_codes() -> None:
    raw = "code-abc"
    for row in (
        {
            "code_hash": LoginCodeRepository.hash_code(raw),
            "consumed_at": "2026-01-01T00:00:00.000Z",
        },
        {
            "code_hash": LoginCodeRepository.hash_code(raw),
            "expires_at": "2000-01-01T00:00:00.000Z",
        },
    ):
        gw = RowGateway(rows=[row])
        repo = LoginCodeRepository(gw)  # type: ignore[arg-type]
        assert await repo.consume(raw) is None
        assert gw.statements == []


def _request(*, scheme: str = "http", forwarded: str | None = "https") -> Request:
    headers = [(b"host", b"fantastic-winner-v83w.onrender.com")]
    if forwarded is not None:
        headers.append((b"x-forwarded-proto", forwarded.encode()))
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": ("fantastic-winner-v83w.onrender.com", 80),
            "root_path": "",
            "path": "/v1/auth/extension/github/callback",
            "query_string": b"",
            "headers": headers,
        }
    )


def test_done_redirect_uses_the_forwarded_https_scheme() -> None:
    # Render terminates TLS; request.base_url alone says http and the extension
    # would never see its done page.
    assert _public_base_url(_request(), AuthConfig()) == (
        "https://fantastic-winner-v83w.onrender.com"
    )


def test_done_redirect_keeps_a_configured_callback_origin() -> None:
    auth = AuthConfig(github_redirect_url="https://api.example.com/v1/auth/extension/github/callback")
    assert _public_base_url(_request(), auth) == "https://api.example.com"


def test_done_redirect_falls_back_to_the_request_scheme_in_local_dev() -> None:
    assert _public_base_url(_request(scheme="http", forwarded=None), AuthConfig()) == (
        "http://fantastic-winner-v83w.onrender.com"
    )
