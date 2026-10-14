"""Shared fixtures.

Tests must never touch PyroCore or an AI provider. Everything here is
constructed in-process so the suite runs offline, in CI, with no secrets.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

# Point Settings at a throwaway project before anything imports it, so a real
# .env in the working tree can never be picked up by a test run.
os.environ.setdefault("PYRONITES_URL", "http://pyronites.invalid")
os.environ.setdefault("PYRONITES_KEY", "pyro_test_key_not_a_real_credential")
os.environ.setdefault("PYRONITES_PROJECT", "test-project")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("ALLOW_OFFLINE_PROVIDER", "true")
os.environ.setdefault("AUTH_AUTO_VERIFY_DEV", "true")
os.environ.setdefault("REQUIRE_VERIFIED_EMAIL_FOR_AI", "false")


@pytest.fixture
def settings():
    from app.core.config import get_settings

    get_settings.cache_clear()
    return get_settings()


@pytest.fixture
def problem() -> dict[str, Any]:
    """A minimal but complete problem payload."""
    return {
        "slug": "two-sum",
        "url": "https://leetcode.com/problems/two-sum/",
        "title": "Two Sum",
        "difficulty": "Easy",
        "statement_text": (
            "Given an array of integers nums and an integer target, return the "
            "indices of the two numbers that add up to target."
        ),
        "constraints_text": "2 <= nums.length <= 10^4",
        "examples": [{"input": "nums = [2,7,11,15], target = 9", "output": "[0,1]"}],
        "editor_language": "python",
    }


class _Batch:
    def __init__(self, rows: list[dict[str, Any]], changes: int) -> None:
        self._rows = rows
        self._changes = changes

    def first(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[dict[str, Any]]:
        return list(self._rows)

    def changes(self, index: int = 0) -> int:
        return self._changes


class FakeGateway:
    """Records statements instead of executing them.

    Lets the SQL-building logic be asserted directly, which is the only way to
    prove the credit model is atomic without a live database.
    """

    def __init__(
        self,
        rows: list[dict[str, Any]] | None = None,
        *,
        error: Exception | None = None,
        changes: int = 1,
    ) -> None:
        self.statements: list[str] = []
        self.rows = rows or []
        self.batches: list[list[str]] = []
        self.error = error
        self.changes_value = changes

    async def execute(self, statements: list[str]) -> Any:
        self.statements.extend(statements)
        self.batches.append(list(statements))
        if self.error is not None:
            raise self.error
        return _Batch(self.rows, self.changes_value)

    async def query_one(self, sql: str) -> dict[str, Any] | None:
        self.statements.append(sql)
        return self.rows[0] if self.rows else None

    async def query_all(self, sql: str) -> list[dict[str, Any]]:
        self.statements.append(sql)
        return list(self.rows)

    async def aclose(self) -> None:
        return None

    @property
    def sql(self) -> str:
        return "\n".join(self.statements)


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def extension_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "extension"