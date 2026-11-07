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
import hashlib
import json
import random
import time
from collections import OrderedDict
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
from . import runtime
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

#: Own-key providers reuse the existing HTTP classes. Nothing else changes:
#: the key is a constructor argument, not a new provider implementation.
_PROVIDER_CLASSES: dict[str, type[OpenAIProvider | AnthropicProvider | GeminiProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
}

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
        # : Per-key provider instances, keyed by sha256 of the raw key. The raw
        # : key is never used as a dictionary key or logged.
        self._byok_providers: OrderedDict[str, tuple[str, Any]] = OrderedDict()

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
        """Attribute spend in the current task to this caller.

        This writes the request-scoped context rather than an attribute on the
        gateway, so two concurrent requests cannot overwrite each other's
        attribution.
        """
        runtime.set_request_context(user_id=user_id, request_id=request_id)

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

        own = list(self._byok_providers.values())
        self._byok_providers.clear()
        for _name, provider in own:
            try:
                await provider.aclose()
            except Exception as exc:
                logger.warning("closing an own-key provider failed: %s", exc)

    async def forget_own_key(self, api_key: str) -> None:
        """Drop a cached provider after its key is removed or rotated."""
        cached = self._byok_providers.pop(_key_digest(api_key), None)
        if cached is None:
            return
        try:
            await cached[1].aclose()
        except Exception as exc:
            logger.warning("closing a removed own-key provider failed: %s", exc)

    async def run(
        self,
        spec: TaskSpec,
        *,
        api_key: str | None = None,
        provider: str | None = None,
    ) -> GatewayResult:
        context = runtime.current_context()
        own_key = api_key or context.api_key
        own_provider = provider or context.provider

        if own_key:
            return await self._run_with_own_key(spec, own_provider, own_key)

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

    async def _run_with_own_key(
        self, spec: TaskSpec, provider_name: str | None, api_key: str
    ) -> GatewayResult:
        """Use exactly one provider, and never fall back to a server key.

        Falling back would silently move the bill to us after the learner asked
        us to use their key. A failure surfaces instead, and the learner can fix
        or replace the key.
        """
        if not provider_name or provider_name not in _PROVIDER_CLASSES:
            raise AiUnavailable("Choose an AI provider before using your own key.")

        semaphore = self._pools[spec.pool]
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self._config.queue_timeout_s)
        except TimeoutError as exc:
            await self._record_spend(
                spec,
                outcome="queue_timeout",
                provider=provider_name,
                cost=0.0,
                funded_by=runtime.FUNDED_BY_USER,
            )
            raise AiBusy("The mentor is busy right now.") from exc

        try:
            provider = await self._provider_for_key(provider_name, api_key)
            digest = _key_digest(api_key)
            return await self._run_with_fallback(
                spec,
                (provider_name,),
                providers={provider_name: provider},
                breaker_scope=digest[:12],
                funded_by=runtime.FUNDED_BY_USER,
            )
        finally:
            semaphore.release()

    async def _provider_for_key(self, name: str, api_key: str) -> Any:
        digest = _key_digest(api_key)
        cached = self._byok_providers.get(digest)
        if cached is not None:
            self._byok_providers.move_to_end(digest)
            return cached[1]

        provider = _PROVIDER_CLASSES[name](api_key, self._config.model_for)
        self._byok_providers[digest] = (name, provider)
        limit = max(1, self._settings.byok.max_cached_providers)
        while len(self._byok_providers) > limit:
            _old_digest, (_old_name, evicted) = self._byok_providers.popitem(last=False)
            try:
                await evicted.aclose()
            except Exception as exc:
                logger.warning("closing an evicted own-key provider failed: %s", exc)
        return provider

    async def _run_with_fallback(
        self,
        spec: TaskSpec,
        order: tuple[str, ...],
        *,
        providers: dict[str, Any] | None = None,
        breaker_scope: str = "",
        funded_by: str = runtime.FUNDED_BY_CODEMENTOR,
    ) -> GatewayResult:
        attempts: list[dict[str, Any]] = []
        last_error: Exception | None = None
        tried: set[str] = set()
        available = providers if providers is not None else self._providers

        for name in order:
            provider = available.get(name)
            if provider is None or not provider.available():
                continue
            if name in tried:
                continue

            breaker_key = f"{name}:{breaker_scope}" if breaker_scope else name
            breaker = self._breakers.for_provider(breaker_key)
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
                    spec,
                    outcome="provider_error",
                    provider=name,
                    cost=0.0,
                    attempts=attempts,
                    funded_by=funded_by,
                )
                last_error = exc
                if not exc.retryable:
                    continue
                continue
            except TimeoutError:
                breaker.record_failure()
                attempts.append(_attempt_row(spec, name, outcome="timeout"))
                await self._record_spend(
                    spec,
                    outcome="timeout",
                    provider=name,
                    cost=0.0,
                    attempts=attempts,
                    funded_by=funded_by,
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
                    funded_by=funded_by,
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
                        funded_by=funded_by,
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
                    funded_by=funded_by,
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
                funded_by=funded_by,
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
            spec,
            outcome="all_providers_failed",
            provider="",
            cost=0.0,
            attempts=attempts,
            funded_by=funded_by,
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
        funded_by: str | None = None,
    ) -> None:
        if self._spend_writer is None:
            return
        context = runtime.current_context()
        model = ""
        if provider:
            model = self._config.model_for(provider, spec.tier)
        try:
            await self._spend_writer(
                request_id=context.request_id or "-",
                user_id=context.user_id or "-",
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
                funded_by=funded_by or context.funded_by,
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

def _key_digest(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


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