"""Token-bucket rate limiting behind an interface (§16.3).

The interface exists so the in-process implementation can be swapped for a shared
one without touching a single caller. That swap is **required before running more
than one backend instance** - an in-process limiter gives each instance its own
full quota, which means N instances grant N times the limit (§24.1).

The bucket shape (burst capacity and refill rate) is passed per call rather than
configured on the limiter, because the shape is a property of the *route class*
and routes are declared on routers, far from where a limiter is constructed.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

from ..core.config import RateLimitConfig


@dataclass(frozen=True)
class BucketSpec:
    capacity: int
    refill_per_min: int

    @property
    def refill_per_s(self) -> float:
        return self.refill_per_min / 60.0

@dataclass(frozen=True)
class Decision:
    allowed: bool
    # : Seconds until the bucket has room again. 0 when allowed.
    retry_after: int = 0
    remaining: int = 0
    limit: int = 0

class RateLimiter(Protocol):
    def allow(self, key: str, spec: BucketSpec, *, cost: int = 1) -> Decision: ...

    def reset(self) -> None: ...

@dataclass
class _Bucket:
    capacity: float
    tokens: float
    refill_per_s: float
    updated_at: float = field(default_factory=time.monotonic)

    def take(self, cost: int, now: float) -> Decision:
        elapsed = max(0.0, now - self.updated_at)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_s)
        self.updated_at = now

        if self.tokens >= cost:
            self.tokens -= cost
            return Decision(allowed=True, remaining=int(self.tokens), limit=int(self.capacity))

        deficit = cost - self.tokens
        return Decision(
            allowed=False,
            retry_after=max(1, int(deficit / max(self.refill_per_s, 1e-9)) + 1),
            remaining=0,
            limit=int(self.capacity),
        )

class InProcessRateLimiter:
    """Token bucket with a monotonic clock and idle-key eviction.

    Correct for a single instance, which is what the initial Render/Fly
    deployment is. The eviction sweep keeps a long-running process from
    accumulating a bucket per IP forever.
    """

    # : Buckets untouched for this long are dropped.
    IDLE_TTL_S = 900.0

    def __init__(self, *, max_buckets: int = 20_000) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()
        self._max_buckets = max_buckets

    def allow(self, key: str, spec: BucketSpec, *, cost: int = 1) -> Decision:
        now = time.monotonic()
        with self._lock:
            self._evict(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                # A new bucket starts full: a burst is allowed, the steady rate
                # is not exceeded afterwards.
                bucket = _Bucket(
                    capacity=float(spec.capacity),
                    tokens=float(spec.capacity),
                    refill_per_s=spec.refill_per_s,
                    updated_at=now,
                )
                self._buckets[key] = bucket
            return bucket.take(cost, now)

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._buckets)

    def _evict(self, now: float) -> None:
        cutoff = now - self.IDLE_TTL_S
        stale = [key for key, bucket in self._buckets.items() if bucket.updated_at < cutoff]
        for key in stale:
            del self._buckets[key]

        if len(self._buckets) > self._max_buckets:
            ordered = sorted(self._buckets.items(), key=lambda item: item[1].updated_at)
            for key, _ in ordered[: len(ordered) // 2]:
                del self._buckets[key]

def bucket_key(user_id: str, route_class: str) -> str:
    return f"l1:{route_class}:{user_id}"

def specs_for(config: RateLimitConfig) -> dict[str, BucketSpec]:
    """Route class to bucket shape, from the table in §16.3."""
    return {
        "light": BucketSpec(config.light_capacity, config.light_refill_per_min),
        "heavy": BucketSpec(config.heavy_capacity, config.heavy_refill_per_min),
        "check": BucketSpec(config.check_capacity, config.check_refill_per_min),
        "analysis": BucketSpec(config.analysis_capacity, config.analysis_refill_per_min),
        "auth": BucketSpec(config.auth_capacity, config.auth_refill_per_min),
    }