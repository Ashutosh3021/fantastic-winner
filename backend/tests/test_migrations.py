from __future__ import annotations

import pytest

from app.migrations import runner


@pytest.mark.asyncio
async def test_ensure_schema_ignores_current_table(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import FakeGateway

    gateway = FakeGateway(
        rows=[
            {
                "sql": (
                    "CREATE TABLE user_ai_credentials (provider TEXT NOT NULL, "
                    "user_id TEXT PRIMARY KEY)"
                )
            }
        ]
    )
    repaired: list[str] = []

    async def fake_run(gateway: object) -> list[str]:
        repaired.append("called")
        return []

    monkeypatch.setattr(runner, "run_migrations", fake_run)

    assert await runner.ensure_schema(gateway) == []
    assert repaired == []


@pytest.mark.asyncio
async def test_ensure_schema_migrates_a_provider_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import FakeGateway

    gateway = FakeGateway(
        rows=[
            {
                "sql": (
                    "CREATE TABLE user_ai_credentials (provider TEXT NOT NULL "
                    "CHECK (provider IN ('openai', 'anthropic', 'gemini')))"
                )
            }
        ]
    )

    async def fake_run(gateway: object) -> list[str]:
        return ["0005"]

    monkeypatch.setattr(runner, "run_migrations", fake_run)

    assert await runner.ensure_schema(gateway) == ["0005"]
    assert any("sqlite_master" in statement for statement in gateway.statements)


@pytest.mark.asyncio
async def test_ensure_schema_survives_an_unreadable_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import FakeGateway

    gateway = FakeGateway(error=RuntimeError("no sqlite_master for you"))

    assert await runner.ensure_schema(gateway) == []


@pytest.mark.asyncio
async def test_refresh_schema_reports_the_ledger() -> None:
    from tests.conftest import FakeGateway

    gateway = FakeGateway(rows=[{"version": "0004"}, {"version": "0005"}])

    assert await runner.refresh_schema(gateway) == "0005"
    assert runner.current_schema == "0005"
    assert any(runner.LEDGER_TABLE in statement for statement in gateway.statements)
