"""Per-request AI call context.

The gateway is process-wide and shared by concurrent requests, so anything that
describes *this* request - whose key paid, who to attribute spend to - cannot be
stored on the object. It lives in a ``ContextVar`` instead: each request task
gets its own value, and no request can read another's key or attribution.

The only request-scoped values here are references and flags. The raw own key is
held for the duration of one request and never written to a log.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass

FUNDED_BY_CODEMENTOR = "codementor"
FUNDED_BY_USER = "user"

_current: ContextVar[AICallContext | None] = ContextVar("ai_call_context", default=None)


@dataclass(frozen=True)
class AICallContext:
    # : Present only for a bring-your-own-key request.
    api_key: str | None = None
    provider: str | None = None
    # : Optional model id chosen with the own key. ``None`` means the
    # : provider's configured default for the task tier.
    model: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    funded_by: str = FUNDED_BY_CODEMENTOR

    @property
    def own_key(self) -> bool:
        return bool(self.api_key and self.provider)

    def with_request(self, *, user_id: str | None, request_id: str | None) -> AICallContext:
        return AICallContext(
            api_key=self.api_key,
            provider=self.provider,
            model=self.model,
            user_id=user_id,
            request_id=request_id,
            funded_by=self.funded_by,
        )


def current_context() -> AICallContext:
    return _current.get() or AICallContext()


def set_context(context: AICallContext) -> Token[AICallContext | None]:
    return _current.set(context)


def reset_context(token: Token[AICallContext | None]) -> None:
    _current.reset(token)


def set_request_context(
    *, user_id: str | None, request_id: str | None
) -> Token[AICallContext | None]:
    """Keep any active BYOK choice while replacing attribution."""
    return _current.set(current_context().with_request(user_id=user_id, request_id=request_id))


__all__ = [
    "FUNDED_BY_CODEMENTOR",
    "FUNDED_BY_USER",
    "AICallContext",
    "current_context",
    "reset_context",
    "set_context",
    "set_request_context",
]
