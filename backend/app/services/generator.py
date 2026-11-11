"""Shared plumbing for every AI-backed service.

Holds the generate-validate-store loop (Â§6.2) in one place so that six services
do not each reimplement it slightly differently:

1. cache lookup (hit â†' return; negative â†' typed error)
2. single-flight so concurrent misses share one call
3. gateway call
4. validation: schema, then the leak policy for this artifact, then quality
5. one regeneration on a leak/quality failure, then a safe fallback
6. store, with a negative-cache entry if the failure was terminal

The loop bounds are fixed: **max 1** schema-repair retry (inside the gateway),
**max 1** leak regeneration, **max 2** provider attempts. Those are not tuning
knobs â-- exceeding them is how a single learner request becomes an unbounded
spend.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel

from ..ai import runtime
from ..ai.gateway import (
    POOL_ANALYSIS,
    POOL_GENERATION,
    POOL_INTERACTIVE,
    AIGateway,
    TaskSpec,
)
from ..ai.prompts import PROMPT_VERSION, system_prompt
from ..cache.store import CacheKeyInput, ContentCache
from ..core.config import Tier
from ..core.errors import AiInvalidOutput, AiKeyRejected, AiUnavailable, DegradedMode
from ..core.logging import get_logger
from ..policies import reveal_boundary as boundary
from ..validators.leak_detector import contains_code, detect_leaks, is_complete_algorithm
from ..validators.quality import QualityReport

logger = get_logger(__name__)

@dataclass
class GenerateRequest:
    """One AI-backed content request."""

    task_id: str
    slug: str
    statement_text: str
    constraints_text: str
    approach_id: str
    language: str
    mode: str
    schema: dict[str, Any]
    adapter: Any
    tier: Tier
    temperature: float
    max_tokens: int
    deadline_s: float
    pool: str = POOL_INTERACTIVE
    content_version: str = PROMPT_VERSION
    variant: str = ""
    # : Example inputs from the problem, for the toy-input similarity check.
    example_inputs: list[str] = field(default_factory=list)

    def cache_key_input(self) -> CacheKeyInput:
        return CacheKeyInput(
            task_id=self.task_id,
            prompt_version=PROMPT_VERSION,
            content_version=self.content_version,
            slug=self.slug,
            server_content_hash=ContentCache.server_content_hash(
                self.statement_text, self.constraints_text
            ),
            approach_id=self.approach_id,
            language=self.language,
            mode=self.mode,
            variant=self.variant,
        )

@dataclass
class GenerateOutcome:
    payload: Any
    cached: bool = False
    cache_key: str = ""
    degraded: bool = False
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0

def collect_artifact_texts(payload: Any, artifact: str) -> list[str]:
    """Every string in a payload that the learner will read.

    The reveal boundary is about *text*, so it has to see all of it â-- including
    diagram captions and data labels, which is where a leak hides if it hides
    anywhere (Â§12.5).
    """
    texts: list[str] = []

    def walk(node: Any, key: str | None = None) -> None:
        if isinstance(node, str):
            if key in {
                "prompt", "simple_explanation", "why_it_fits_this_problem",
                "common_beginner_mistake", "humour_line", "feedback", "text",
                "title", "alt_text", "caption", "why", "label", "summary",
                "items", "quote", "why_it_fits", "learning_goal",
            }:
                texts.append(node)
        elif isinstance(node, dict):
            for child_key, value in node.items():
                walk(value, child_key)
        elif isinstance(node, list):
            for value in node:
                walk(value, key)

    walk(payload)
    if artifact == "checklist" and isinstance(payload, dict):
        for item in payload.get("items", []) or []:
            if isinstance(item, str):
                texts.append(item)
    return texts

def _cached_error(code: str | None) -> Exception:
    """Rebuild the typed error a negative-cache entry stands for."""
    if code == "ai_key_rejected":
        return AiKeyRejected(
            "The provider rejected your API key. Open the CodeMentor popup and "
            "check that the key matches the selected provider."
        )
    if code == "ai_invalid_output":
        return AiInvalidOutput(
            "The generated answer did not pass the quality checks. Nothing was charged."
        )
    return AiUnavailable("That is temporarily unavailable. Nothing was charged.")

class ContentGenerator:
    def __init__(
        self, gateway: AIGateway, cache: ContentCache, budget: Any
    ) -> None:
        self.gateway = gateway
        self.cache = cache
        self.budget = budget

    async def generate(
        self,
        request: GenerateRequest,
        *,
        system: str,
        user: str,
        client_ip: str | None = None,
    ) -> GenerateOutcome:
        key = request.cache_key_input()

        cached = await self.cache.lookup(key)
        if cached.negative:
            # A cached outage or key failure was recorded before this learner
            # supplied (or replaced) their own key. Their retry costs CodeMentor
            # nothing, and honouring the entry would keep a fixed key looking
            # broken until the negative TTL expired.
            if runtime.current_context().own_key and cached.error_code in (
                "ai_unavailable",
                "ai_key_rejected",
            ):
                pass
            else:
                raise _cached_error(cached.error_code)
        if cached.hit:
            return GenerateOutcome(
                payload=cached.payload, cached=True, cache_key=cache_key_str(key)
            )

        await self.budget.require_not_degraded()

        artifact = boundary.TASK_ARTIFACT.get(request.task_id, "concept_card")

        async def _produce() -> GenerateOutcome:
            spec = TaskSpec(
                task_id=request.task_id,
                prompt_version=PROMPT_VERSION,
                system=system,
                user=user,
                schema=request.schema,
                tier=request.tier,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                deadline_s=request.deadline_s,
                pool=request.pool,
                adapter=request.adapter,
            )
            result = await self.gateway.run(spec)
            payload = self._check(payload=result.payload, request=request, artifact=artifact)
            return GenerateOutcome(
                payload=payload,
                cache_key=key.compute(),
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=result.cost_usd,
            )

        try:
            outcome = await self.cache.single_flight(key.compute(), _produce)
        except AiKeyRejected:
            # About this learner's key, not about the problem. Caching it would
            # punish everyone else who shares the cache key.
            raise
        except (AiUnavailable, DegradedMode) as exc:
            # Terminal for this key: remember it so nobody re-pays to rediscover.
            await self.cache.store_negative(key, error_code=exc.code)
            raise
        except AiInvalidOutput:
            await self.cache.store_negative(key, error_code="ai_invalid_output")
            raise
        except Exception as exc:
            if getattr(exc, "code", "") not in (
                "ai_output_truncated",
                "ai_key_rejected",
            ):
                await self.cache.store_negative(
                    key, error_code=str(getattr(exc, "code", "ai_unavailable"))
                )
            raise

        if not outcome.cached:
            await self.cache.store(
                key,
                payload=outcome.payload,
                tokens_in=outcome.tokens_in,
                tokens_out=outcome.tokens_out,
            )

        if client_ip:
            await self.budget.charge_ip(
                client_ip=client_ip, tokens=outcome.tokens_in + outcome.tokens_out
            )

        return cast("GenerateOutcome", outcome)

    def _check(self, *, payload: Any, request: GenerateRequest, artifact: str) -> Any:
        """Schema (already done by the gateway) â†' leak policy â†' quality."""
        policies = boundary.policies_for(artifact)
        mode = boundary.effective_mode(policies)
        texts = collect_artifact_texts(payload, artifact)

        for text in texts:
            # The code check runs for every policy, EARNED included: nothing in
            # the product ever contains code (--11.2).
            if contains_code(text):
                raise AiInvalidOutput(f"leak:code in {artifact}")
            report = detect_leaks(text, language=request.language)
            if report.clean:
                continue
            # Algorithm-completeness is the only check EARNED and STEP_SCOPED
            # are exempt from, and only because by then the learner has already
            # written the algorithm as their own answers.
            if mode == "STRICT" and is_complete_algorithm(text):
                raise AiInvalidOutput(f"leak:complete_algorithm in {artifact}")
            raise AiInvalidOutput(f"leak:{report.reasons()[0]} in {artifact}")

        return payload

def cache_key_str(key: CacheKeyInput) -> str:
    return key.compute()

def dump_schema(model: type[BaseModel]) -> dict[str, Any]:
    """JSON Schema for a pydantic model, for the provider's structured output."""
    schema: dict[str, Any] = model.model_json_schema(mode="serialization")
    return schema

def build_system(*, language: str, mode: str) -> str:
    return system_prompt(language=language, mode=mode)

def schema_for(model: type[BaseModel]) -> dict[str, Any]:
    try:
        return dump_schema(model)
    except Exception:
        logger.exception("could not build schema for %s", model)
        return {"type": "object"}

def ensure_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []

def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)

POOLS = {
    "interactive": POOL_INTERACTIVE,
    "generation": POOL_GENERATION,
    "analysis": POOL_ANALYSIS,
}

def quality_ok(report: QualityReport) -> bool:
    return report.ok