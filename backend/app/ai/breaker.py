"""Circuit breaker per provider (§16.8 control 5).

Opens after N failures inside a rolling window, stays open for a cooldown, then
lets exactly one probe through. While it is open, requests route to the fallback
immediately rather than waiting to discover the provider is still down.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _State:
    failures: list[float] = field(default_factory=list)
    opened_at: float | None = None
    probing: bool = False

class CircuitBreaker:
    def __init__(
        self,
        *,
        name: str,
        failures_threshold: int = 5,
        window_s: float = 30.0,
        open_s: float = 60.0,
    ) -> None:
        self.name = name
        self._threshold = failures_threshold
        self._window = window_s
        self._open_s = open_s
        self._state = _State()

    def allows(self, *, now: float | None = None) -> bool:
        """Whether a request may be sent. Consumes the half-open probe slot."""
        now = now if now is not None else time.monotonic()
        self._prune(now)

        if self._state.opened_at is None:
            return True

        if now - self._state.opened_at < self._open_s:
            return False

        # Cooldown elapsed: allow exactly one probe.
        if self._state.probing:
            return False
        self._state.probing = True
        return True

    def record_success(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self._state.failures.clear()
        self._state.opened_at = None
        self._state.probing = False
        del now

    def record_failure(self, *, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        self._state.probing = False
        self._state.failures.append(now)
        if len(self._state.failures) >= self._threshold:
            self._state.opened_at = now

    @property
    def is_open(self) -> bool:
        return self._state.opened_at is not None

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        self._state.failures = [t for t in self._state.failures if t >= cutoff]

class BreakerRegistry:
    def __init__(self, *, failures_threshold: int, window_s: float, open_s: float) -> None:
        self._kwargs: dict[str, Any] = {
            "failures_threshold": failures_threshold,
            "window_s": window_s,
            "open_s": open_s,
        }
        self._breakers: dict[str, CircuitBreaker] = {}

    def for_provider(self, name: str) -> CircuitBreaker:
        breaker = self._breakers.get(name)
        if breaker is None:
            breaker = CircuitBreaker(name=name, **self._kwargs)
            self._breakers[name] = breaker
        return breaker

    def open_providers(self) -> list[str]:
        return [name for name, breaker in self._breakers.items() if breaker.is_open]

    def reset(self) -> None:
        self._breakers.clear()