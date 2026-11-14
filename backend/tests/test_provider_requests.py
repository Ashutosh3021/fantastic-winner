"""Wire-level provider parameters that are easy to get wrong silently."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.ai.providers import GroqProvider, OpenAIProvider


def _wire(provider: Any, captured: dict[str, Any], *, content: str = "{}") -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": captured["body"]["model"],
                "choices": [
                    {"message": {"content": content}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def _call(provider: Any) -> None:
    await provider.generate_json(
        system="system",
        user="user",
        schema={"type": "object"},
        tier="fast",
        temperature=0.0,
        max_tokens=64,
        deadline_s=5.0,
    )
    await provider.aclose()


class TestGroqBody:
    async def test_gpt_oss_uses_low_reasoning_effort(self) -> None:
        captured: dict[str, Any] = {}
        provider = GroqProvider("gsk-test", lambda _name, _tier: "openai/gpt-oss-120b")
        await provider._client.aclose()
        _wire(provider, captured)

        await _call(provider)

        assert captured["body"]["reasoning_effort"] == "low"

    async def test_llama_does_not_get_a_rejected_parameter(self) -> None:
        captured: dict[str, Any] = {}
        provider = GroqProvider("gsk-test", lambda _name, _tier: "llama-3.3-70b-versatile")
        await provider._client.aclose()
        _wire(provider, captured)

        await _call(provider)

        assert "reasoning_effort" not in captured["body"]

    async def test_openai_never_sends_groq_only_parameters(self) -> None:
        captured: dict[str, Any] = {}
        provider = OpenAIProvider("sk-test", lambda _name, _tier: "gpt-4o-mini")
        await provider._client.aclose()
        _wire(provider, captured)

        await _call(provider)

        assert "reasoning_effort" not in captured["body"]
