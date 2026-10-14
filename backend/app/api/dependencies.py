"""Request-scoped dependencies: identity, idempotency, client IP.

The identity dependency is the security boundary for the whole API. It reads one
opaque bearer token, looks up its hash, and returns an :class:`Identity`. It
never accepts a user id from the request, because a route that trusts a
client-supplied owner id is one refactor away from leaking another learner's
sessions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from ..core.errors import BadRequest, RateLimited, Unauthorized
from ..core.logging import get_logger, hash_user_id
from ..ratelimit.limiter import BucketSpec
from ..services.auth_service import Identity
from .deps import Container, get_container

logger = get_logger(__name__)

#: Opaque tokens are urlsafe base64; anything else is a probe or a mistake.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-.]{20,200}$")

_NO_PEER = "no-peer"


@dataclass(frozen=True)
class Caller:
    """Who is asking, and from where."""

    identity: Identity
    client_ip: str
    idempotency_key: str | None


def get_container_dep(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - only if startup failed
        raise Unauthorized("Service is not ready")
    return container


ContainerDep = Annotated[Container, Depends(get_container_dep)]


def client_ip_of(request: Request) -> str:
    """Best-effort client address.

    ``X-Forwarded-For`` is only trustworthy behind a proxy that sets it, so a
    configured proxy count is applied and anything past that is ignored: letting
    a client spoof ``X-Forwarded-For`` would let it bypass the per-IP AI budget.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    trusted: int = int(getattr(request.app.state, "trusted_proxy_count", 0))
    if forwarded and trusted > 0:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if len(parts) > trusted:
            return parts[-trusted]
    if request.client is not None:
        host: str = request.client.host
        return host
    # No peer address (a unix socket or a test transport). Named rather than
    # faked as an IP so it is obvious in a budget log that the request could not
    # be attributed to an address.
    return _NO_PEER


async def get_caller(
    request: Request,
    container: ContainerDep,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Caller:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in to continue.")

    raw = authorization.split(" ", 1)[1].strip()
    if not _TOKEN_RE.match(raw):
        # Rejecting the shape before the database lookup keeps a junk token from
        # becoming a hash-and-query on every request.
        raise Unauthorized("Sign in to continue.")

    identity = await container.auth.identity_for(raw)
    request.state.identity = identity

    return Caller(
        identity=identity,
        client_ip=client_ip_of(request),
        idempotency_key=idempotency_key,
    )


CallerDep = Annotated[Caller, Depends(get_caller)]


def require_idempotency_key(caller: Caller) -> str:
    """The key for a route that spends credits or writes state.

    Required rather than optional on purpose. A missing key means a client
    cannot retry safely, so failing loudly beats charging a learner twice for
    one click.
    """
    if not caller.idempotency_key:
        raise BadRequest("This request needs an Idempotency-Key header.")
    key = caller.idempotency_key.strip()
    if len(key) > 200:
        raise BadRequest("Idempotency-Key is too long.")
    return key


#: Route classes, matching the extension's own classification. A "heavy" route
#: costs a real generation, so it gets a much smaller bucket than a read.
_BUCKETS: dict[str, tuple[str, str]] = {
    "light": ("light_capacity", "light_refill_per_min"),
    "heavy": ("heavy_capacity", "heavy_refill_per_min"),
    "check": ("check_capacity", "check_refill_per_min"),
    "analysis": ("analysis_capacity", "analysis_refill_per_min"),
    "auth": ("light_capacity", "light_refill_per_min"),
}


def enforce_rate_limit(
    container: Container, caller: Caller, *, route_class: str = "light", cost: int = 1
) -> None:
    """Refuse a caller who is over the bucket for this route class.

    Keyed on a hash of the user id, not the raw value: the limiter holds these
    keys in memory, and a plaintext user id in a process dump is a record of who
    is using the service. The per-IP AI budget in the budget service covers the
    "one household, many learners" case separately.
    """
    capacity_attr, refill_attr = _BUCKETS.get(route_class, _BUCKETS["light"])
    config = container.settings.rate_limits
    spec = BucketSpec(
        capacity=int(getattr(config, capacity_attr)),
        refill_per_min=int(getattr(config, refill_attr)),
    )
    decision = container.rate_limiter.allow(
        f"{route_class}:{hash_user_id(caller.identity.user_id)}", spec, cost=cost
    )
    if not decision.allowed:
        raise RateLimited(
            "Too many requests just now. Try again in a moment.",
            retry_after_sec=decision.retry_after,
        )


__all__ = [
    "Caller",
    "CallerDep",
    "ContainerDep",
    "client_ip_of",
    "enforce_rate_limit",
    "get_caller",
    "get_container",
    "require_idempotency_key",
]
