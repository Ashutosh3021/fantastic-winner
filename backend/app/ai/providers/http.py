"""HTTP providers: OpenAI, Gemini and Anthropic.

All three are spoken to over plain HTTP rather than through their vendor SDKs.
That is a deliberate trade: the gateway only needs "given this system prompt,
this user prompt and this JSON schema, return JSON", which is one POST each, and
it keeps the dependency set small enough that adding a provider is one file
rather than a package decision.

Every provider reports ``finish_reason`` faithfully. Truncation is not an error
condition to be retried â-- it is information the gateway acts on (Â§15.3).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx

from ...core.logging import get_logger
from .base import FinishReason, ProviderError, ProviderResult, Tier

logger = get_logger(__name__)

def _decode(text: str) -> Any:
    """Pull JSON out of a response, tolerating a fenced wrapper."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: -3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # A provider that narrates around the JSON is a recoverable shape error;
        # the gateway's repair path exists for exactly this.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end > start:
            return json.loads(cleaned[start : end + 1])
        raise

class OpenAIProvider:
    name = "openai"
    base_url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model_for: Callable[[str, Tier], str]) -> None:
        self._api_key = api_key
        self._model_for = model_for
        # One client for the provider's lifetime: connection pooling across
        # requests, and a socket that is actually closed at shutdown.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def available(self) -> bool:
        return bool(self._api_key)

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tier: Tier,
        temperature: float,
        max_tokens: int,
        deadline_s: float,
    ) -> ProviderResult:
        body = {
            "model": self._model_for(self.name, tier),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{user}\n\nReturn JSON matching this schema:\n"
                    f"{json.dumps(schema, ensure_ascii=False)}",
                },
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self._client.post(
                self.base_url,
                timeout=deadline_s,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {type(exc).__name__}") from exc

        if not response.is_success:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}",
                retryable=response.status_code in (429, 500, 502, 503, 504),
                status=response.status_code,
            )

        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        finish = choice.get("finish_reason") or "stop"
        return ProviderResult(
            text=message.get("content") or "",
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            finish_reason=(
                FinishReason.LENGTH if finish == "length" else FinishReason.STOP
            ),
            raw={"model": data.get("model", "")},
        )

class GroqProvider(OpenAIProvider):
    """Groq speaks OpenAI's chat wire format; only host and name differ."""

    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"


class AnthropicProvider:
    name = "anthropic"
    base_url = "https://api.anthropic.com/v1/messages"
    version = "2023-06-01"

    def __init__(self, api_key: str, model_for: Callable[[str, Tier], str]) -> None:
        self._api_key = api_key
        self._model_for = model_for
        # One client for the provider's lifetime: connection pooling across
        # requests, and a socket that is actually closed at shutdown.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def available(self) -> bool:
        return bool(self._api_key)

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tier: Tier,
        temperature: float,
        max_tokens: int,
        deadline_s: float,
    ) -> ProviderResult:
        body = {
            "model": self._model_for(self.name, tier),
            "system": system,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = await self._client.post(
                self.base_url,
                timeout=deadline_s,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": self.version,
                    "content-type": "application/json",
                },
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {type(exc).__name__}") from exc

        if not response.is_success:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}",
                retryable=response.status_code in (429, 500, 502, 503, 529),
                status=response.status_code,
            )

        data = response.json()
        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = data.get("usage") or {}
        finish = data.get("stop_reason") or "end_turn"
        return ProviderResult(
            text=text,
            tokens_in=int(usage.get("input_tokens", 0)),
            tokens_out=int(usage.get("output_tokens", 0)),
            finish_reason=(
                FinishReason.LENGTH if finish == "max_tokens" else FinishReason.STOP
            ),
            raw={"model": data.get("model", "")},
        )

class GeminiProvider:
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, model_for: Callable[[str, Tier], str]) -> None:
        self._api_key = api_key
        self._model_for = model_for
        # One client for the provider's lifetime: connection pooling across
        # requests, and a socket that is actually closed at shutdown.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))

    async def aclose(self) -> None:
        await self._client.aclose()

    def available(self) -> bool:
        return bool(self._api_key)

    async def generate_json(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        tier: Tier,
        temperature: float,
        max_tokens: int,
        deadline_s: float,
    ) -> ProviderResult:
        model = self._model_for(self.name, tier)
        url = f"{self.base_url}/{model}:generateContent?key={self._api_key}"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        try:
            response = await self._client.post(
                url,
                timeout=deadline_s,
                headers={"content-type": "application/json"},
                json=body,
            )
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name}: {type(exc).__name__}") from exc

        if not response.is_success:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}",
                retryable=response.status_code in (429, 500, 502, 503),
                status=response.status_code,
            )

        data = response.json()
        candidates = data.get("candidates") or [{}]
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata") or {}
        finish = candidates[0].get("finishReason") or "STOP"
        return ProviderResult(
            text=text,
            tokens_in=int(usage.get("promptTokenCount", 0)),
            tokens_out=int(usage.get("candidatesTokenCount", 0)),
            finish_reason=(
                FinishReason.LENGTH if finish == "MAX_TOKENS" else FinishReason.STOP
            ),
            raw={"model": model},
        )

ALL_PROVIDERS: tuple[type, ...] = (
    OpenAIProvider,
    AnthropicProvider,
    GeminiProvider,
    GroqProvider,
)