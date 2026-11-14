"""Plan tiers and bring-your-own-key behaviour.

These tests are deliberately about the boundaries that are easy to get wrong:

* a raw key never appears in a response, a repr or a stored row;
* an own key never silently falls back to a server key;
* the enforcement matrix is enforced where credits and budgets are claimed, not
  merely displayed in the UI.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.ai import runtime
from app.ai.gateway import AIGateway, TaskSpec
from app.ai.providers import FinishReason, ProviderError, ProviderResult
from app.api.routers.learning import _spend_credit
from app.core.config import ByokConfig, ProviderKeys, Settings
from app.core.errors import (
    AiKeyRejected,
    AiOutputTruncated,
    AiUnavailable,
    BadRequest,
    ByokUnavailable,
)
from app.repositories.store import SpendRepository, UserAICredentialRepository
from app.schemas.models import AIKeyInput, AIKeyView, MeResponse
from app.services.auth_service import Identity
from app.services.budget_service import BudgetService
from app.services.byok_service import ByokService
from app.services.progress_service import ProgressService
from tests.conftest import FakeGateway

SERVER_KEY = "server-key-for-tests"
USER_KEY = "sk-user-own-key-1234"
GROQ_KEY = "gsk-user-own-key-1234"


# ── storage and encryption ──────────────────────────────────────────────────


class _StubCredentialRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def for_user(self, user_id: str) -> dict[str, Any] | None:
        return self.rows.get(user_id)

    async def upsert(
        self, *, user_id: str, provider: str, ciphertext: str, hint: str
    ) -> dict[str, Any]:
        row = {
            "user_id": user_id,
            "provider": provider,
            "key_ciphertext": ciphertext,
            "key_hint": hint,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        self.rows[user_id] = row
        return row

    async def delete_for_user(self, user_id: str) -> bool:
        return self.rows.pop(user_id, None) is not None


def _config(key: str | None = None) -> ByokConfig:
    return ByokConfig(encryption_key=key or Fernet.generate_key().decode())


class TestEncryption:
    async def test_round_trip_produces_metadata_not_a_key(self) -> None:
        repo = _StubCredentialRepo()
        service = ByokService(repo, _config())

        view = await service.save(user_id="u1", provider="openai", api_key=USER_KEY)

        assert view == {
            "provider": "openai",
            "hint": "1234",
            "model": None,
            "updatedAt": "2026-01-01T00:00:00Z",
        }
        assert USER_KEY not in str(view)
        stored = repo.rows["u1"]
        assert stored["key_ciphertext"] != USER_KEY
        assert service.decrypt(stored["key_ciphertext"]) == USER_KEY

    async def test_missing_encryption_key_fails_closed(self) -> None:
        service = ByokService(_StubCredentialRepo(), ByokConfig(encryption_key=""))
        with pytest.raises(ByokUnavailable):
            await service.save(user_id="u1", provider="openai", api_key=USER_KEY)

    async def test_fallback_secret_keeps_byok_available(self) -> None:
        repo = _StubCredentialRepo()
        config = ByokConfig(fallback_secret="pyro_live_example")
        service = ByokService(repo, config)

        view = await service.save(user_id="u1", provider="openai", api_key=USER_KEY)

        assert view["hint"] == "1234"
        assert service.decrypt(repo.rows["u1"]["key_ciphertext"]) == USER_KEY

        # The derived key is stable, so a second service instance reads the row.
        reloaded = ByokService(_StubCredentialRepo(), config)
        assert reloaded.decrypt(repo.rows["u1"]["key_ciphertext"]) == USER_KEY

    async def test_explicit_key_wins_over_the_fallback_secret(self) -> None:
        key = Fernet.generate_key().decode()
        repo = _StubCredentialRepo()
        explicit = ByokService(repo, ByokConfig(encryption_key=key, fallback_secret="ignored"))
        await explicit.save(user_id="u1", provider="openai", api_key=USER_KEY)

        derived = ByokService(
            _StubCredentialRepo(), ByokConfig(fallback_secret="ignored")
        )
        with pytest.raises(ByokUnavailable):
            derived.decrypt(repo.rows["u1"]["key_ciphertext"])

    async def test_malformed_encryption_key_fails_closed(self) -> None:
        service = ByokService(_StubCredentialRepo(), ByokConfig(encryption_key="nope"))
        with pytest.raises(ByokUnavailable):
            service.encrypt(USER_KEY)

    async def test_remove_metadata_does_not_require_decryption(self) -> None:
        repo = _StubCredentialRepo()
        service = ByokService(repo, _config())
        await service.save(user_id="u1", provider="gemini", api_key=USER_KEY)
        await service.remove("u1")
        assert await service.metadata("u1") is None

    async def test_groq_key_and_model_round_trip(self) -> None:
        repo = _StubCredentialRepo()
        service = ByokService(repo, _config())

        view = await service.save(
            user_id="u1",
            provider="groq",
            api_key=GROQ_KEY,
            model="openai/gpt-oss-120b",
        )

        assert view["provider"] == "groq"
        assert view["model"] == "openai/gpt-oss-120b"
        assert GROQ_KEY not in str(view)
        metadata = await service.metadata("u1")
        assert metadata is not None and metadata["model"] == "openai/gpt-oss-120b"
        assert service.decrypt_row(repo.rows["u1"]) == (
            "groq",
            GROQ_KEY,
            "openai/gpt-oss-120b",
        )

    async def test_rows_written_without_a_model_still_read(self) -> None:
        repo = _StubCredentialRepo()
        service = ByokService(repo, _config())
        await service.save(user_id="u1", provider="openai", api_key=USER_KEY)

        repo.rows["u1"]["key_ciphertext"] = service.encrypt(USER_KEY)

        assert service.decrypt_row(repo.rows["u1"]) == ("openai", USER_KEY, None)
        metadata = await service.metadata("u1")
        assert metadata is not None and metadata["model"] is None

    async def test_invalid_model_id_is_rejected(self) -> None:
        service = ByokService(_StubCredentialRepo(), _config())

        with pytest.raises(BadRequest):
            await service.save(
                user_id="u1", provider="groq", api_key=GROQ_KEY, model="not a model"
            )

    def test_model_is_validated_at_the_schema_boundary(self) -> None:
        inbound = AIKeyInput(
            provider="groq", api_key=GROQ_KEY, model="openai/gpt-oss-120b"
        )
        assert inbound.model == "openai/gpt-oss-120b"

        with pytest.raises(ValidationError):
            AIKeyInput(provider="groq", api_key=GROQ_KEY, model="bad model!")

    def test_groq_is_a_first_class_provider(self) -> None:
        from app.ai.gateway import _PROVIDER_CLASSES
        from app.ai.providers import GroqProvider
        from app.core.config import GatewayConfig

        assert _PROVIDER_CLASSES["groq"] is GroqProvider
        assert GroqProvider.base_url == "https://api.groq.com/openai/v1/chat/completions"
        assert GatewayConfig().model_for("groq", "fast")

    def test_secret_str_and_response_models_never_leak_the_key(self) -> None:
        inbound = AIKeyInput(provider="openai", api_key=USER_KEY)
        assert USER_KEY not in repr(inbound)
        assert USER_KEY not in inbound.model_dump_json()

        view = AIKeyView(provider="openai", hint="1234", updatedAt="2026-01-01T00:00:00Z")
        assert USER_KEY not in view.model_dump_json()

        me = MeResponse(
            id="u1",
            email="learner@example.com",
            email_verified=True,
            created_at="2026-01-01T00:00:00Z",
            preferences={},  # type: ignore[arg-type]
            usage={},
            planTier=1,
            aiKey=view,
        )
        assert USER_KEY not in me.model_dump_json()


class TestCredentialRepositorySql:
    async def test_upsert_and_delete_use_the_user_id_primary_key(self) -> None:
        gw = FakeGateway()
        repo = UserAICredentialRepository(gw)

        await repo.upsert(
            user_id="u1",
            provider="anthropic",
            ciphertext="ciphertext-not-a-key",
            hint="1234",
        )
        sql = gw.sql
        assert "INSERT INTO user_ai_credentials" in sql
        assert "'u1'" in sql
        assert "ciphertext-not-a-key" in sql

        await repo.delete_for_user("u1")
        assert "DELETE FROM user_ai_credentials" in gw.sql


# ── gateway routing ─────────────────────────────────────────────────────────


def _spec() -> TaskSpec:
    return TaskSpec(
        task_id="concept_card",
        prompt_version="test",
        system="system",
        user="user",
        schema={"type": "object"},
        tier="fast",
        temperature=0.0,
        max_tokens=64,
        deadline_s=2.0,
    )


def _settings() -> Settings:
    return Settings(
        keys=ProviderKeys(openai=SERVER_KEY),
        byok=ByokConfig(encryption_key=Fernet.generate_key().decode()),
    )


class _RecordingProvider:
    created_with: ClassVar[list[str]] = []

    def __init__(self, api_key: str, model_for: Any) -> None:
        self.name = "openai"
        self.api_key = api_key
        self._model_for = model_for
        self.__class__.created_with.append(api_key)

    def available(self) -> bool:
        return True

    async def aclose(self) -> None:
        return None

    async def generate_json(self, **_: Any) -> Any:
        raise ProviderError("openai: HTTP 401", retryable=False, status=401)


class _MissingModelProvider(_RecordingProvider):
    async def generate_json(self, **_: Any) -> Any:
        raise ProviderError("gemini: HTTP 404", retryable=False, status=404)


class _FencedJsonProvider(_RecordingProvider):
    calls: ClassVar[int] = 0

    async def generate_json(self, **_: Any) -> Any:
        type(self).calls += 1
        return ProviderResult(text='```json\n{"answer": 42}\n```', tokens_in=3, tokens_out=4)


class _FencedOnRepairProvider(_RecordingProvider):
    calls: ClassVar[int] = 0

    async def generate_json(self, **_: Any) -> Any:
        type(self).calls += 1
        if type(self).calls == 1:
            return ProviderResult(text="Here you go: not json")
        return ProviderResult(text='```json\n{"answer": 7}\n```', tokens_in=3, tokens_out=4)


class TestOwnKeyRouting:
    async def test_own_key_does_not_fall_back_to_the_server_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _RecordingProvider.created_with.clear()
        rows: list[dict[str, Any]] = []

        async def spend(**fields: Any) -> None:
            rows.append(fields)

        monkeypatch.setattr("app.ai.gateway._PROVIDER_CLASSES", {"openai": _RecordingProvider})
        gateway = AIGateway(_settings(), spend_writer=spend)
        server_calls: list[str] = []

        async def server_generate(**_: Any) -> Any:
            server_calls.append("called")
            raise AssertionError("server provider must not be reached")

        gateway._providers["openai"].generate_json = server_generate  # type: ignore[method-assign]

        with pytest.raises(AiUnavailable):
            await gateway.run(_spec(), api_key=USER_KEY, provider="openai")
        assert server_calls == []
        assert _RecordingProvider.created_with == [USER_KEY]
        assert rows and all(row["funded_by"] == "user" for row in rows)
        await gateway.aclose()

    async def test_rejected_own_key_names_the_key_as_the_problem(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.ai.gateway._PROVIDER_CLASSES", {"openai": _RecordingProvider})
        gateway = AIGateway(_settings())

        with pytest.raises(AiKeyRejected) as raised:
            await gateway.run(_spec(), api_key=USER_KEY, provider="openai")

        assert "rejected your API key" in str(raised.value)
        assert raised.value.status == 422
        await gateway.aclose()

    async def test_retired_model_names_the_model_not_the_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.ai.gateway._PROVIDER_CLASSES", {"openai": _MissingModelProvider}
        )
        gateway = AIGateway(_settings())

        with pytest.raises(AiKeyRejected) as raised:
            await gateway.run(_spec(), api_key=USER_KEY, provider="openai")

        assert "no such model" in str(raised.value)
        await gateway.aclose()

    async def test_custom_model_builds_a_provider_for_that_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "app.ai.gateway._PROVIDER_CLASSES", {"openai": _RecordingProvider}
        )
        gateway = AIGateway(_settings())

        default = await gateway._provider_for_key("openai", USER_KEY)
        custom = await gateway._provider_for_key("openai", USER_KEY, "custom-model")

        assert default is not custom
        assert custom._model_for("openai", "fast") == "custom-model"

        await gateway.forget_own_key(USER_KEY)
        assert not gateway._byok_providers
        await gateway.aclose()

    async def test_context_key_is_used_when_no_argument_is_passed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _RecordingProvider.created_with.clear()
        monkeypatch.setattr("app.ai.gateway._PROVIDER_CLASSES", {"openai": _RecordingProvider})
        gateway = AIGateway(_settings())

        token = runtime.set_context(
            runtime.AICallContext(api_key=USER_KEY, provider="openai", funded_by="user")
        )
        try:
            with pytest.raises(AiUnavailable):
                await gateway.run(_spec())
        finally:
            runtime.reset_context(token)

        assert _RecordingProvider.created_with == [USER_KEY]
        await gateway.aclose()

    async def test_removed_key_evicts_its_cached_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("app.ai.gateway._PROVIDER_CLASSES", {"openai": _RecordingProvider})
        gateway = AIGateway(_settings())
        await gateway._provider_for_key("openai", USER_KEY)
        assert len(gateway._byok_providers) == 1

        await gateway.forget_own_key(USER_KEY)
        assert gateway._byok_providers == {}
        await gateway.aclose()

    async def test_fenced_json_from_the_provider_is_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _FencedJsonProvider.calls = 0
        monkeypatch.setattr(
            "app.ai.gateway._PROVIDER_CLASSES", {"openai": _FencedJsonProvider}
        )
        gateway = AIGateway(_settings())

        result = await gateway.run(_spec(), api_key=USER_KEY, provider="openai")

        assert result.payload == {"answer": 42}
        assert _FencedJsonProvider.calls == 1
        await gateway.aclose()

    async def test_repair_accepts_fenced_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _FencedOnRepairProvider.calls = 0
        monkeypatch.setattr(
            "app.ai.gateway._PROVIDER_CLASSES", {"openai": _FencedOnRepairProvider}
        )
        gateway = AIGateway(_settings())

        result = await gateway.run(_spec(), api_key=USER_KEY, provider="openai")

        assert result.payload == {"answer": 7}
        assert _FencedOnRepairProvider.calls == 2
        await gateway.aclose()


class _TruncatingProvider(_RecordingProvider):
    """Truncates once, then answers. Records the budget of every call."""

    budgets: ClassVar[list[int]] = []

    async def generate_json(self, **kwargs: Any) -> Any:
        type(self).budgets.append(kwargs["max_tokens"])
        if len(type(self).budgets) == 1:
            return ProviderResult(
                text="",
                tokens_in=11,
                tokens_out=kwargs["max_tokens"],
                finish_reason=FinishReason.LENGTH,
            )
        return ProviderResult(text='{"answer": 42}', tokens_in=11, tokens_out=7)


class TestOwnKeyTruncation:
    async def test_own_key_retries_once_with_a_larger_budget(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _TruncatingProvider.budgets.clear()
        rows: list[dict[str, Any]] = []

        async def spend(**fields: Any) -> None:
            rows.append(fields)

        monkeypatch.setattr(
            "app.ai.gateway._PROVIDER_CLASSES", {"openai": _TruncatingProvider}
        )
        gateway = AIGateway(_settings(), spend_writer=spend)

        result = await gateway.run(_spec(), api_key=USER_KEY, provider="openai")

        assert result.payload == {"answer": 42}
        assert _TruncatingProvider.budgets == [64, 128]
        assert [row["outcome"] for row in rows] == ["truncated", "ok"]
        await gateway.aclose()

    async def test_shared_budget_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _TruncatingProvider.budgets.clear()
        gateway = AIGateway(_settings())
        gateway._providers["openai"] = _TruncatingProvider(  # type: ignore[assignment]
            SERVER_KEY, gateway._config.model_for
        )

        with pytest.raises(AiOutputTruncated) as raised:
            await gateway.run(_spec())

        assert _TruncatingProvider.budgets == [64]
        assert raised.value.extra == {
            "provider": "openai",
            "model": "",
            "max_tokens": 64,
            "task": "concept_card",
        }
        await gateway.aclose()


# ── enforcement matrix ──────────────────────────────────────────────────────


class _CreditsProbe:
    def __init__(self) -> None:
        self.claims = 0

    async def claim(self, **_: Any) -> Any:
        self.claims += 1
        return SimpleNamespace(acquired=True)


class _Caller:
    def __init__(self, identity: Identity) -> None:
        self.identity = identity


def _identity(*, plan_tier: int, has_own_key: bool) -> Identity:
    return Identity(
        user_id="u1",
        email="learner@example.com",
        email_verified=True,
        account_age_days=30,
        plan_tier=plan_tier,
        has_own_key=has_own_key,
    )


async def _claim_for(identity: Identity) -> tuple[bool, int]:
    credits = _CreditsProbe()
    charged = await _spend_credit(
        SimpleNamespace(credits=credits),
        _Caller(identity),
        "idem-1",
        "session-1",
        reserve_n=3,
    )
    return charged, credits.claims


class TestEnforcementMatrix:
    async def test_tier_zero_own_key_still_burns_credits(self) -> None:
        charged, claims = await _claim_for(_identity(plan_tier=0, has_own_key=True))
        assert charged is True
        assert claims == 1

    async def test_tier_one_own_key_skips_the_claim(self) -> None:
        charged, claims = await _claim_for(_identity(plan_tier=1, has_own_key=True))
        assert charged is False
        assert claims == 0

    async def test_tier_one_without_a_key_stays_metered(self) -> None:
        charged, claims = await _claim_for(_identity(plan_tier=1, has_own_key=False))
        assert charged is True
        assert claims == 1

    async def test_tier_zero_server_key_is_metered(self) -> None:
        charged, claims = await _claim_for(_identity(plan_tier=0, has_own_key=False))
        assert charged is True
        assert claims == 1


class _ForbiddenBudgetRepo:
    async def daily_calls(self, **_: Any) -> int:
        raise AssertionError("own-key requests must not touch the IP budget")

    async def record_call(self, **_: Any) -> None:
        raise AssertionError("own-key requests must not touch the IP budget")


class _ForbiddenSpendRepo:
    async def spend_since(self, **_: Any) -> tuple[float, int]:
        raise AssertionError("own-key requests must not touch the daily spend cap")

    async def tokens_for_user_since(self, **_: Any) -> int:
        raise AssertionError("own-key requests must not touch the user token budget")


class TestBudgetsSkippedForOwnKey:
    async def test_degraded_mode_is_ignored_for_an_own_key(self) -> None:
        budget = BudgetService(
            Settings(degraded_mode=True),
            _ForbiddenSpendRepo(),  # type: ignore[arg-type]
            _ForbiddenBudgetRepo(),  # type: ignore[arg-type]
        )
        token = runtime.set_context(
            runtime.AICallContext(api_key=USER_KEY, provider="openai", funded_by="user")
        )
        try:
            await budget.require_not_degraded()
            await budget.charge_ip(client_ip="203.0.113.9", tokens=1_000)
        finally:
            runtime.reset_context(token)


class TestSpendAttribution:
    async def test_funded_by_is_persisted(self) -> None:
        gw = FakeGateway()
        inserted: list[dict[str, Any]] = []

        async def insert_row(table: str, row: dict[str, Any]) -> None:
            inserted.append({"table": table, "row": row})

        gw.insert_row = insert_row  # type: ignore[attr-defined]
        repo = SpendRepository(gw)

        await repo.record(user_id="u1", funded_by="user", cost_usd=0.01)

        assert inserted[0]["row"]["funded_by"] == "user"

    async def test_budget_queries_exclude_user_funded_rows(self) -> None:
        gw = FakeGateway()
        repo = SpendRepository(gw)

        await repo.query_since("2026-01-01T00:00:00Z")
        await repo.tokens_for_user_since(user_id="u1", since_iso="2026-01-01T00:00:00Z")

        assert gw.sql.count("funded_by") >= 2


# ── /me and route auth ──────────────────────────────────────────────────────


class _Users:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row

    async def get(self, _user_id: str) -> dict[str, Any]:
        return self.row


class _Prefs:
    async def get(self, _user_id: str) -> dict[str, Any]:
        return {
            "language": "en",
            "difficulty_mode": "beginner",
            "theme": "system",
            "timezone": "UTC",
            "prefs_version": 1,
        }


class TestMeShape:
    async def test_me_carries_tier_and_key_metadata(self) -> None:
        service = ProgressService(
            FakeGateway(),
            users=_Users(  # type: ignore[arg-type]
                {
                    "id": "u1",
                    "email": "learner@example.com",
                    "email_verified_at": "2026-01-01T00:00:00Z",
                    "created_at": "2026-01-01T00:00:00Z",
                    "plan_tier": 1,
                }
            ),
            preferences=_Prefs(),  # type: ignore[arg-type]
            mistakes=SimpleNamespace(),  # type: ignore[arg-type]
            saved_cards=SimpleNamespace(),  # type: ignore[arg-type]
            credit_config=Settings().credits,
        )

        payload = await service.me(
            "u1",
            usage={},
            ai_key={"provider": "openai", "hint": "1234", "updatedAt": "2026-01-01T00:00:00Z"},
        )

        assert payload["planTier"] == 1
        assert payload["aiKey"]["hint"] == "1234"
        assert USER_KEY not in str(payload)

    async def test_me_defaults_to_tier_zero_without_a_key(self) -> None:
        service = ProgressService(
            FakeGateway(),
            users=_Users(  # type: ignore[arg-type]
                {
                    "id": "u1",
                    "email": "learner@example.com",
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ),
            preferences=_Prefs(),  # type: ignore[arg-type]
            mistakes=SimpleNamespace(),  # type: ignore[arg-type]
            saved_cards=SimpleNamespace(),  # type: ignore[arg-type]
            credit_config=Settings().credits,
        )
        payload = await service.me("u1", usage={})
        assert payload["planTier"] == 0
        assert payload["aiKey"] is None


class TestKeyRoutesRequireAuth:
    async def test_get_put_and_delete_are_rejected_without_a_token(self) -> None:
        from app.main import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/v1/account/ai-key")).status_code == 401
            put = await client.put(
                "/v1/account/ai-key",
                json={"provider": "openai", "api_key": USER_KEY},
            )
            assert put.status_code == 401
            assert (await client.delete("/v1/account/ai-key")).status_code == 401
