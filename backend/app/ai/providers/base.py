"""AI provider abstraction (Â§15.2).

Providers are addressed through one small protocol so that a swap â-- or an
outage â-- is a list change, not a code change. Business rules never live here:
the gateway owns retries, budgets, caching and attribution, and a provider's
only job is to turn a request into structured output and report honestly how
that went.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ...core.config import Tier as Tier
from ...core.errors import AppError, UpstreamError


class FinishReason:
    STOP = "stop"
    # : Hit the output budget. Deterministic: the same prompt and the same budget
    # : truncate the same way, which is why it is never retried (--15.3).
    LENGTH = "length"
    ERROR = "error"

@dataclass(frozen=True)
class ProviderResult:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = FinishReason.STOP
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        return self.finish_reason == FinishReason.LENGTH

class ProviderError(UpstreamError):
    """A provider failed in a way that may be worth retrying or falling back on."""

    def __init__(self, message: str, *, retryable: bool = True, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.provider_status = status

class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    async def aclose(self) -> None:
        """Release the provider's HTTP connections.

        Part of the protocol because a provider that holds a pooled client owns
        a socket; the gateway closes them all on shutdown.
        """
        ...

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
    ) -> ProviderResult: ...

class OfflineProvider:
    """Deterministic generator for local development and CI.

    It returns schema-shaped output derived from the prompt, so the whole
    request pipeline â-- validation, leak checking, caching, credit accounting â--
    can be exercised end to end with no API key and no network. It is not a
    tutor and must never serve real learners: :meth:`available` returns False
    unless ``ALLOW_OFFLINE_PROVIDER=true`` *and* no real key is configured.
    """

    name = "offline"

    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    async def aclose(self) -> None:
        """No sockets to release."""

    def available(self) -> bool:
        return self._enabled

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
        import json

        payload = _offline_payload(schema, user)
        text = json.dumps(payload, ensure_ascii=False)
        return ProviderResult(
            text=text,
            tokens_in=len(system.split()) + len(user.split()),
            tokens_out=len(text.split()),
            finish_reason=FinishReason.STOP,
            raw={"provider": "offline"},
        )

def _offline_payload(schema: dict[str, Any], user: str) -> dict[str, Any]:
    """Build the smallest object that satisfies `schema`, guided by the prompt."""
    import re

    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", list(properties))

    # Pull a problem slug or title out of the prompt so offline content is at
    # least problem-shaped rather than boilerplate.
    slug_match = re.search(r"slug[:=]\s*([a-z0-9-]+)", user)
    slug = slug_match.group(1) if slug_match else "this problem"

    out: dict[str, Any] = {}
    for name in required:
        spec = properties.get(name, {})
        out[name] = _offline_value(name, spec, slug)
    return out

def _offline_value(name: str, spec: dict[str, Any], slug: str) -> Any:
    if "enum" in spec:
        return spec["enum"][0]
    kind = spec.get("type")
    if kind == "string":
        if name == "prompt":
            return f"What is the first thing you would work out for {slug}?"
        if name in ("why_it_fits_this_problem", "complexity_explanation"):
            return (
                f"In {slug}, the shape of the input decides which technique fits, "
                "so the constraints tell you what is even possible."
            )
        if name == "common_beginner_mistake":
            return "Starting with the answer instead of the data the answer is about."
        if name == "simple_explanation":
            return (
                "Start by naming what the problem gives you and what it asks back. "
                "Everything else follows from that pair."
            )
        return f"[offline:{name}]"
    if kind == "number":
        minimum = spec.get("minimum", 0)
        return float(minimum) if isinstance(minimum, float) else int(minimum)
    if kind == "integer":
        return int(spec.get("minimum", 0))
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return {
            key: _offline_value(key, sub, slug)
            for key, sub in spec.get("properties", {}).items()
        }
    return None

def provider_error(name: str, detail: str, *, retryable: bool = True) -> AppError:
    return ProviderError(f"{name}: {detail}", retryable=retryable)