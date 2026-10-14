"""The AI gateway (Â§15.2, Â§15.3, Â§16.8).

One entry point, `run`, and the guarantees it makes:

* **Truncation is detected, not retried.** A response that reports
  ``finish_reason == length`` raises ``ai_output_truncated`` immediately. The
  same prompt against the same budget truncates the same way every time, so a
  retry loop here spends money and latency to arrive at the same failure.
* **Every exit path writes spend.** Success, provider failure, validation
  failure, truncation. Failed calls are the expensive ones and were invisible in
  v1's accounting, which is exactly when you need to see them.
* **Business rules never live here.** Caching, credits, leak policy and session
  state are the services' job; this module owns provider selection, concurrency,
  retry, fallback and attribution â-- nothing else.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from ..core.config import GatewayConfig, Settings, Tier
from ..core.errors import (
    AiBusy,
    AiInvalidOutput,
    AiOutputTruncated,
    AiUnavailable,
    UpstreamError,
)
from ..core.logging import get_logger, hash_user_id
from .breaker import BreakerRegistry
from .providers import (
    AnthropicProvider,
    FinishReason,
    GeminiProvider,
    OfflineProvider,
    OpenAIProvider,
    Provider,
    ProviderError,
    ProviderResult,
)

logger = get_logger(__name__)

# : Pools, so a heavy generation cannot starve an interactive answer check.
POOL_INTERACTIVE = "interactive"
POOL_GENERATION = "generation"
POOL_ANALYSIS = "analysis"

_POOL_SIZE: dict[str, str] = {
    POOL_INTERACTIVE: "concurrency_interactive",
    POOL_GENERATION: "concurrency_generation",
    POOL_ANALYSIS: "concurrency_analysis",
}

@dataclass(frozen=True)
class TaskSpec:
    """Everything the gateway needs, and nothing about the caller."""

    task_id: str
    prompt_version: str
    system: str
    user: str
    schema: dict[str, Any]
    tier: Tier
    temperature: float
    max_tokens: int
    deadline_s: float
    pool: str = POOL_INTERACTIVE
    # : When set, one repair retry is permitted if schema validation fails.
    adapter: Callable[[Any], Any] | None = None

@dataclass
class GatewayResult:
    payload: Any
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int
    finish_reason: str
    # : One entry per attempt, so ``ai_spend`` can be written per attempt.
    attempts: list[dict[str, Any]] = field(default_factory=list)

SpendWriter = Callable[..., Awaitable[None]]

class AIGateway:
    def __init__(
        self,
        settings: Settings,
        *,
        spend_writer: SpendWriter | None = None,
    ) -> None:
        self._settings = settings
        self._config: GatewayConfig = settings.gateway
        self._spend_writer = spend_writer
        self._breakers = BreakerRegistry(
            failures_threshold=self._config.breaker_failures,
            window_s=self._config.breaker_window_s,
            open_s=self._config.breaker_open_s,
        )
        self._providers = self._build_providers(settings)
        self._pools = self._build_pools()
        # : Filled in by the request context so spend rows carry user attribution.
        self._current_user_id: str | None = None
        self._current_request_id: str | None = None

    # --- construction ---

    def _build_providers(self, settings: Settings) -> dict[str, Provider]:
        model_for = settings.gateway.model_for
        providers: dict[str, Provider] = {
            "openai": OpenAIProvider(settings.keys.openai, model_for),
            "anthropic": AnthropicProvider(settings.keys.anthropic, model_for),
            "gemini": GeminiProvider(settings.keys.gemini, model_for),
        }
        # The offline provider is a *last* resort and only exists when explicitly
        # enabled with no real key configured, so it can never shadow a real one.
        if settings.allow_offline_provider and not settings.keys.any_configured():
            providers["offline"] = OfflineProvider(enabled=True)
        return providers

    def _build_pools(self) -> dict[str, asyncio.Semaphore]:
        sizes = {
            POOL_INTERACTIVE: self._config.concurrency_interactive,
            POOL_GENERATION: self._config.concurrency_generation,
            POOL_ANALYSIS: self._config.concurrency_analysis,
        }
        return {pool: asyncio.Semaphore(max(1, size)) for pool, size in sizes.items()}

    def bind_request(self, *, user_id: str | None, request_id: str | None) -> None:
        """Attribute every spend row written until the next bind."""
        self._current_user_id = user_id
        self._current_request_id = request_id

    def provider_names(self) -> list[str]:
        return sorted(self._providers)

    # --- the main entry point ---

    async def aclose(self) -> None:
        """Close every provider's HTTP client.

        Providers hold pooled connections, so they must be closed exactly once on
        shutdown rather than garbage-collected per request.
        """
        for name, provider in self._providers.items():
            close = getattr(provider, "aclose", None)
            if close is None:
                continue
            try:
                await close()
            except Exception as exc:
                logger.warning("closing provider %s failed: %s", name, exc)

    async def run(self, spec: TaskSpec) -> GatewayResult:
        order = self._config.provider_order.get(spec.tier, ("openai",))
        semaphore = self._pools[spec.pool]

        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._config.queue_timeout_s)
        except TimeoutError as exc:
            await self._record_spend(spec, outcome="queue_timeout", provider="", cost=0.0)
            raise AiBusy("The mentor is busy right now.") from exc

        try:
            return await self._run_with_fallback(spec, order)
        finally:
            semaphore.release()

    async def _run_with_fallback(self, spec: TaskSpec, order: tuple[str, ...]) -> GatewayResult:
        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        tried: set[str] = set()

        for name in order:
            provider = self._providers.get(name)
            if provider is None or not provider.available():
                continue
            if name in tried:
                continue

            breaker = self._breakers.for_provider(name)
            if not breaker.allows():
                logger.info("breaker open, skipping provider %s", name)
                continue
            tried.add(name)

            try:
                attempt = await self._attempt(spec, provider)
            except ProviderError as exc:
                breaker.record_failure()
                attempts.append(_attempt_row(spec, name, outcome="provider_error"))
                await self._record_spend(
                    spec, outcome="provider_error", provider=name, cost=0.0, attempts=attempts
                )
                last_error = exc
                if not exc.retryable:
                    continue
                continue
            except TimeoutError:
                breaker.record_failure()
                attempts.append(_attempt_row(spec, name, outcome="timeout"))
                await self._record_spend(
                    spec, outcome="timeout", provider=name, cost=0.0, attempts=attempts
                )
                last_error = UpstreamError(f"{name} timed out")
                continue

            breaker.record_success()
            result = attempt.result

            if result.truncated:
                # --15.3 --- no repair retry, no fallback. The budget is the cause.
                cost = self._cost(result)
                await self._record_spend(
                    spec,
                    outcome="truncated",
                    provider=name,
                    cost=cost,
                    attempts=attempts,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    finish_reason=result.finish_reason,
                )
                raise AiOutputTruncated(
                    "The response reached its length budget before finishing."
                )

            validated = await self._validate(spec, attempt)
            if validated is None:
                attempts.append(
                    _attempt_row(
                        spec,
                        name,
                        outcome="schema_invalid",
                        tokens_in=result.tokens_in,
                        tokens_out=result.tokens_out,
                    )
                )
                # One repair retry only (--6.2). If that fails the artifact is not
                # deliverable and the caller gets a typed error with no charge.
                repaired = await self._repair(spec, provider, attempt)
                if repaired is None:
                    cost = self._cost(result)
                    await self._record_spend(
                        spec,
                        outcome="schema_invalid",
                        provider=name,
                        cost=cost,
                        attempts=attempts,
                        tokens_in=result.tokens_in,
                        tokens_out=result.tokens_out,
                    )
                    raise AiInvalidOutput("The response did not match the expected shape.")

                breaker.record_success()
                repaired_result = repaired.result
                cost = self._cost(repaired_result)
                await self._record_spend(
                    spec,
                    outcome="ok",
                    provider=name,
                    cost=cost,
                    attempts=attempts,
                    tokens_in=repaired_result.tokens_in,
                    tokens_out=repaired_result.tokens_out,
                )
                return GatewayResult(
                    payload=repaired.payload,
                    provider=name,
                    model=str(repaired_result.raw.get("model", "")),
                    tokens_in=repaired_result.tokens_in,
                    tokens_out=repaired_result.tokens_out,
                    cost_usd=cost,
                    duration_ms=repaired.duration_ms,
                    finish_reason=repaired_result.finish_reason,
                    attempts=attempts,
                )

            cost = self._cost(result)
            await self._record_spend(
                spec,
                outcome="ok",
                provider=name,
                cost=cost,
                attempts=attempts,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                finish_reason=result.finish_reason,
            )
            return GatewayResult(
                payload=validated,
                provider=name,
                model=str(result.raw.get("model", "")),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=cost,
                duration_ms=attempt.duration_ms,
                finish_reason=result.finish_reason,
                attempts=attempts,
            )

        await self._record_spend(
            spec, outcome="all_providers_failed", provider="", cost=0.0, attempts=attempts
        )
        logger.warning(
            "all providers failed for %s (%s): %s",
            spec.task_id,
            spec.prompt_version,
            type(last_error).__name__ if last_error else "no provider available",
        )
        raise AiUnavailable("No AI provider is currently available.")

    # --- one provider call ---

    async def _attempt(self, spec: TaskSpec, provider: Provider) -> _Attempt:
        started = time.monotonic()
        attempts_left = max(1, self._config.max_attempts_per_request)
        backoff = self._config.backoff_base_s
        last: ProviderError | None = None

        for _ in range(attempts_left):
            try:
                result = await asyncio.wait_for(
                    provider.generate_json(
                        system=spec.system,
                        user=spec.user,
                        schema=spec.schema,
                        tier=spec.tier,
                        temperature=spec.temperature,
                        max_tokens=spec.max_tokens,
                        deadline_s=spec.deadline_s,
                    ),
                    timeout=spec.deadline_s,
                )
            except TimeoutError as exc:
                last = ProviderError(f"{provider.name}: deadline exceeded")
                last.__cause__ = exc
            except ProviderError as exc:
                last = exc
            else:
                return _Attempt(
                    provider=provider.name,
                    result=result,
                    duration_ms=int((time.monotonic() - started) * 1000),
                )

            if not last.retryable:
                raise last
            # Jitter for retry backoff. Deliberately not cryptographic: the
            # threat here is synchronised retries from many clients, not a
            # predictable value an attacker can exploit.
            await asyncio.sleep(backoff * (0.5 + random.random()))  # noqa: S311
            backoff = min(backoff * 2, self._config.backoff_cap_s)

        raise last or ProviderError(f"{provider.name}: exhausted attempts")

    # --- validation and repair ---

    async def _validate(self, spec: TaskSpec, attempt: _Attempt) -> Any | None:
        try:
            payload = json.loads(attempt.result.text)
        except json.JSONDecodeError:
            return None
        if spec.adapter is not None:
            try:
                return spec.adapter(payload)
            except (ValidationError, ValueError, KeyError, TypeError):
                return None
        return payload

    async def _repair(
        self, spec: TaskSpec, provider: Provider, attempt: _Attempt
    ) -> _Attempt | None:
        """Exactly one repair retry, and only after a genuine shape error (Â§6.2)."""
        repair = TaskSpec(
            task_id=spec.task_id,
            prompt_version=spec.prompt_version,
            system=spec.system,
            user=(
                "Your previous reply was not valid JSON for the required schema.\n"
                f"Reply was: {attempt.result.text[:600]}\n\n"
                "Return ONLY the corrected JSON object. No prose."
            ),
            schema=spec.schema,
            tier=spec.tier,
            temperature=0.0,
            max_tokens=spec.max_tokens,
            deadline_s=spec.deadline_s,
            pool=spec.pool,
            adapter=spec.adapter,
        )
        try:
            retry = await asyncio.wait_for(
                provider.generate_json(
                    system=repair.system,
                    user=repair.user,
                    schema=repair.schema,
                    tier=repair.tier,
                    temperature=repair.temperature,
                    max_tokens=repair.max_tokens,
                    deadline_s=repair.deadline_s,
                ),
                timeout=repair.deadline_s,
            )
        except (TimeoutError, ProviderError):
            return None

        if retry.finish_reason == FinishReason.LENGTH:
            return None
        try:
            payload = json.loads(retry.text)
        except json.JSONDecodeError:
            return None
        if spec.adapter is not None:
            try:
                spec.adapter(payload)
            except (ValidationError, ValueError, KeyError, TypeError):
                return None
        return _Attempt(
            provider=provider.name,
            result=retry,
            duration_ms=attempt.duration_ms,
            payload=payload,
        )

    # --- spend attribution ---

    def _cost(self, result: ProviderResult) -> float:
        per_mtok_in = self._config.cost_per_mtok_in
        per_mtok_out = self._config.cost_per_mtok_out
        return round(
            (result.tokens_in * per_mtok_in + result.tokens_out * per_mtok_out) / 1_000_000,
            6,
        )

    async def _record_spend(
        self,
        spec: TaskSpec,
        *,
        outcome: str,
        provider: str,
        cost: float,
        attempts: list[dict[str, Any]] | None = None,
        tokens_in: int = 0,
        tokens_out: int = 0,
        finish_reason: str | None = None,
    ) -> None:
        if self._spend_writer is None:
            return
        model = ""
        if provider:
            model = self._config.model_for(provider, spec.tier)
        try:
            await self._spend_writer(
                request_id=self._current_request_id or "-",
                user_id=self._current_user_id or "-",
                task_id=spec.task_id,
                prompt_version=spec.prompt_version,
                provider=provider or "-",
                model=model or "-",
                tier=spec.tier,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cached=False,
                cost_usd=cost,
                outcome=outcome,
                finish_reason=finish_reason,
                attempts=len(attempts or []),
            )
        except Exception:
            logger.exception("failed to record ai_spend")

@dataclass
class _Attempt:
    provider: str
    result: ProviderResult
    duration_ms: int
    payload: Any = None

    @property
    def truncated(self) -> bool:
        return self.result.truncated

def _attempt_row(spec: TaskSpec, provider: str, *, outcome: str, **extra: Any) -> dict[str, Any]:
    row = {
        "task_id": spec.task_id,
        "provider": provider,
        "outcome": outcome,
        "prompt_version": spec.prompt_version,
        "user_id_hash": hash_user_id(None),
    }
    row.update(extra)
    return row

def adapter_for(model: type[BaseModel]) -> Callable[[Any], Any]:
    """Turn a pydantic model into a validating adapter for ``TaskSpec``."""

    def _adapter(payload: Any) -> Any:
        return TypeAdapter(model).validate_python(payload)

    return _adapter