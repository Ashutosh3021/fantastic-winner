"""A negative cache entry must not hide a provider failure from an own key.

The cache key describes the task and the problem, not the provider or model.
Before this rule, an ``ai_invalid_output`` recorded against one model was served
to every learner until the TTL expired, including one who had just switched
providers and was paying for the retry with their own key.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from app.ai import runtime
from app.ai.gateway import GatewayResult
from app.cache.store import CacheLookup
from app.core.errors import AiInvalidOutput
from app.services.generator import ContentGenerator, GenerateRequest, collect_artifact_texts

KEY = "sk-own-key-1234"


class _Card(BaseModel):
    summary: str


class _Cache:
    def __init__(self, lookup: CacheLookup) -> None:
        self._lookup = lookup
        self.negatives: list[str] = []
        self.stored: list[Any] = []

    async def lookup(self, key: Any) -> CacheLookup:
        return self._lookup

    async def single_flight(self, cache_key: str, factory: Any) -> Any:
        return await factory()

    async def store(
        self, key: Any, *, payload: Any, tokens_in: int = 0, tokens_out: int = 0
    ) -> None:
        json.dumps(payload)
        self.stored.append(payload)

    async def store_negative(self, key: Any, *, error_code: str) -> None:
        self.negatives.append(error_code)


class _Budget:
    async def require_not_degraded(self) -> None:
        return None

    async def charge_ip(self, *, client_ip: str, tokens: int) -> None:
        return None


class _Gateway:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, spec: Any) -> GatewayResult:
        self.calls += 1
        payload = (
            spec.adapter({"summary": "A useful way to think about it."})
            if spec.adapter is not None
            else {"summary": "A useful way to think about it."}
        )
        return GatewayResult(
            payload=payload,
            provider="openai",
            model="test",
            tokens_in=1,
            tokens_out=1,
            cost_usd=0.0,
            duration_ms=1,
            finish_reason="stop",
        )


def _request() -> GenerateRequest:
    return GenerateRequest(
        task_id="analysis.v1",
        slug="two-sum",
        statement_text="Find two numbers that add up to the target.",
        constraints_text="Each input has exactly one answer.",
        approach_id="hash-map",
        language="python",
        mode="beginner",
        schema={"type": "object"},
        adapter=_Card.model_validate,
        tier="fast",
        temperature=0.0,
        max_tokens=64,
        deadline_s=2.0,
    )


async def _generate(
    lookup: CacheLookup, *, own_key: bool
) -> tuple[Any, _Gateway, _Cache]:
    gateway, cache = _Gateway(), _Cache(lookup)
    generator = ContentGenerator(gateway, cache, _Budget())  # type: ignore[arg-type]
    token = runtime.set_context(
        runtime.AICallContext(
            api_key=KEY if own_key else None,
            provider="groq" if own_key else None,
        )
    )
    try:
        outcome = await generator.generate(_request(), system="system", user="user")
    finally:
        runtime.reset_context(token)
    return outcome, gateway, cache


async def test_own_key_ignores_a_cached_invalid_output() -> None:
    outcome, gateway, _ = await _generate(
        CacheLookup(negative=True, error_code="ai_invalid_output"), own_key=True
    )

    assert gateway.calls == 1
    assert outcome.payload.summary


async def test_model_payloads_are_stored_as_json_objects() -> None:
    _, _, cache = await _generate(CacheLookup(), own_key=True)

    assert cache.stored == [{"summary": "A useful way to think about it."}]


def test_collect_artifact_texts_reads_pydantic_models() -> None:
    assert collect_artifact_texts(_Card(summary="hello"), "analysis_fragments") == [
        "hello"
    ]


async def test_cache_hits_are_revalidated_into_the_adapter_type() -> None:
    outcome, gateway, _ = await _generate(
        CacheLookup(hit=True, payload={"summary": "cached"}), own_key=True
    )

    assert gateway.calls == 0
    assert isinstance(outcome.payload, _Card)
    assert outcome.payload.summary == "cached"


async def test_a_stale_cache_hit_is_regenerated() -> None:
    outcome, gateway, cache = await _generate(
        CacheLookup(hit=True, payload={"nope": 1}), own_key=True
    )

    assert gateway.calls == 1
    assert outcome.payload.summary
    assert cache.stored == [{"summary": "A useful way to think about it."}]


async def test_server_key_still_honors_a_cached_invalid_output() -> None:
    with pytest.raises(AiInvalidOutput):
        await _generate(
            CacheLookup(negative=True, error_code="ai_invalid_output"), own_key=False
        )
