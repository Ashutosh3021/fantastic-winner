"""Content cache: cross-user, server-keyed, single-flight, negative (§15.8).

Three defects in v1 drove this design, and each has a specific fix here:

1. **Cache-key forgery.** ``content_hash`` was the client's and went straight
   into the key. Varying whitespace minted unlimited distinct keys, each
   triggering a real generation - a scraper could burn the free tier's budget
   without ever sending a real problem. Now the server normalises the text and
   hashes *its own* result; the client's hash is a drift hint and is ignored.

2. **Key collapse.** Two learners whose extracted statements differed by trailing
   whitespace got two cache rows and two generations for identical content. The
   same normalisation collapses them.

3. **No negative cache.** A key that failed for a real reason was re-attempted
   and re-paid by every subsequent request. Failures were a revenue stream. Now
   a terminal failure is cached for ``NEGATIVE_CACHE_TTL_S`` and returned
   instantly.

``single_flight`` is what stops fifty simultaneous first-requests for the same
problem becoming fifty generations.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import unicodedata
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.config import CacheConfig
from ..core.logging import get_logger
from ..repositories.gateway import PyronitesGateway
from ..repositories.sql import encode, encode_json, safe_identifier
from ..repositories.store import ContentCacheRepository, new_id, now_iso

logger = get_logger(__name__)

_WHITESPACE = re.compile(r"\s+")

#: Zero-width and bidi marks, stripped so a cosmetic edit cannot fork a cache
#: key. Written with explicit escapes: the previous literal-character form
#: compiled into a character class that also matched ordinary letters, which
#: emptied every normalised string and gave every learner the same cache key.
_INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060\ufeff]")

def normalise_text(text: str) -> str:
    """NFKC, invisible characters removed, whitespace collapsed, trimmed.

    Deliberately lossy on whitespace: two statements that differ only in
    formatting *are* the same problem, and they must share a cache row.
    """
    if not text:
        return ""
    stripped = _INVISIBLE.sub("", text)
    normalised = unicodedata.normalize("NFKC", stripped)
    return _WHITESPACE.sub(" ", normalised).strip()

def canonical_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    slug = re.sub(r"^/+|/+$", "", slug)
    slug = re.sub(r"[^a-z0-9-]+", "-", slug)
    return slug.strip("-")

@dataclass(frozen=True)
class CacheKeyInput:
    task_id: str
    prompt_version: str
    content_version: str
    slug: str
    server_content_hash: str
    approach_id: str = ""
    language: str = "en"
    mode: str = "beginner"
    variant: str = ""

    def compute(self) -> str:
        raw = "|".join(
            [
                self.task_id,
                self.prompt_version,
                self.content_version,
                canonical_slug(self.slug),
                self.server_content_hash,
                self.approach_id,
                self.language,
                self.mode,
                self.variant,
            ]
        )
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

@dataclass
class CacheLookup:
    hit: bool = False
    payload: Any = None
    negative: bool = False
    error_code: str | None = None
    cache_key: str = ""

@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    negatives: int = 0
    fills: int = 0

class ContentCache:
    def __init__(
        self,
        gateway: PyronitesGateway,
        config: CacheConfig,
        *,
        repository: ContentCacheRepository | None = None,
    ) -> None:
        self.gw = gateway
        self.config = config
        self.repo = repository or ContentCacheRepository(gateway)
        self.stats = CacheStats()
        self._in_flight: dict[str, asyncio.Task[Any]] = {}
        self._fill_bucket: asyncio.Semaphore | None = None
        self._fill_capacity = config.fill_per_min

    # -- key derivation ---

    @staticmethod
    def server_content_hash(statement_text: str, constraints_text: str) -> str:
        """Hash the server's own normalised text. The client's value is ignored.

        This is the single most important function in the file: it is what stops
        a client from minting unlimited cache keys by varying whitespace.
        """
        canonical = normalise_text(statement_text) + "\n" + normalise_text(constraints_text)
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def drift_detected(client_hash: str | None, server_hash: str) -> bool:
        """A mismatch means our extraction changed; it is logged, never trusted."""
        return bool(client_hash) and client_hash != server_hash

    # -- read path ---

    async def lookup(self, key: CacheKeyInput) -> CacheLookup:
        cache_key = key.compute()
        row = await self.gw.query_one(
            f"SELECT payload_json, negative, error_code, expires_at FROM "
            f"{safe_identifier(self.repo.table)} WHERE cache_key = {encode(cache_key)}"
        )
        if row is None:
            self.stats.misses += 1
            return CacheLookup(cache_key=cache_key)

        if str(row.get("expires_at", "")) <= now_iso():
            self.stats.misses += 1
            return CacheLookup(cache_key=cache_key)

        if int(row.get("negative") or 0) == 1:
            # Re-attempting a terminal failure is how failures became a revenue
            # stream. Return the cached error until the TTL expires.
            self.stats.negatives += 1
            return CacheLookup(
                negative=True,
                error_code=str(row.get("error_code") or "ai_unavailable"),
                cache_key=cache_key,
            )

        import json

        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except json.JSONDecodeError:
            self.stats.misses += 1
            return CacheLookup(cache_key=cache_key)

        self.stats.hits += 1
        return CacheLookup(hit=True, payload=payload, cache_key=cache_key)

    # -- write path ---

    async def store(
        self,
        key: CacheKeyInput,
        *,
        payload: Any,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        expires = datetime.now(UTC) + timedelta(days=self.config.ttl_days)
        await self.gw.execute(
            [
                f"INSERT OR REPLACE INTO {safe_identifier(self.repo.table)} "
                "(cache_key, task_id, prompt_version, content_version, slug_family, approach_id, "
                "language, mode, payload_json, tokens_in, tokens_out, negative, error_code, "
                "created_at, expires_at) VALUES ("
                f"{encode(key.compute())}, {encode(key.task_id)}, {encode(key.prompt_version)}, "
                f"{encode(key.content_version)}, {encode(canonical_slug(key.slug))}, "
                f"{encode(key.approach_id)}, {encode(key.language)}, {encode(key.mode)}, "
                f"{encode_json(payload)}, {encode(int(tokens_in))}, {encode(int(tokens_out))}, "
                f"0, NULL, {encode(now_iso())}, {encode(_iso(expires))})"
            ]
        )
        self.stats.fills += 1
        await self._enforce_per_slug_cap(canonical_slug(key.slug))

    async def store_negative(self, key: CacheKeyInput, *, error_code: str) -> None:
        """Remember a terminal failure so nobody re-pays to rediscover it."""
        expires = datetime.now(UTC) + timedelta(seconds=self.config.negative_ttl_s)
        await self.gw.execute(
            [
                f"INSERT OR REPLACE INTO {safe_identifier(self.repo.table)} "
                "(cache_key, task_id, prompt_version, content_version, slug_family, approach_id, "
                "language, mode, payload_json, tokens_in, tokens_out, negative, error_code, "
                "created_at, expires_at) VALUES ("
                f"{encode(key.compute())}, {encode(key.task_id)}, {encode(key.prompt_version)}, "
                f"{encode(key.content_version)}, {encode(canonical_slug(key.slug))}, "
                f"{encode(key.approach_id)}, {encode(key.language)}, {encode(key.mode)}, "
                f"'{{}}', 0, 0, 1, {encode(error_code)}, {encode(now_iso())}, "
                f"{encode(_iso(expires))})"
            ]
        )
        self.stats.negatives += 1

    async def _enforce_per_slug_cap(self, slug_family: str) -> None:
        """Bound how many rows one problem can occupy (§15.8).

        Without this, a forged or merely noisy key stream would grow the table
        without limit for a single popular problem.
        """
        if not slug_family:
            return
        row = await self.gw.query_one(
            f"SELECT COUNT(*) AS n FROM {safe_identifier(self.repo.table)} "
            f"WHERE slug_family = {encode(slug_family)}"
        )
        count = int(row["n"]) if row else 0
        if count <= self.config.max_rows_per_slug:
            return
        overflow = count - self.config.max_rows_per_slug
        await self.gw.execute(
            [
                f"DELETE FROM {safe_identifier(self.repo.table)} WHERE cache_key IN ("
                f"SELECT cache_key FROM {safe_identifier(self.repo.table)} "
                f"WHERE slug_family = {encode(slug_family)} "
                f"ORDER BY created_at ASC LIMIT {encode(int(overflow))})"
            ]
        )

    # -- single flight ---

    async def single_flight(
        self, cache_key: str, factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Any:
        """Share one in-flight generation across identical concurrent misses.

        Covers failures too, so fifty simultaneous first-requests produce one
        call and one outcome rather than fifty.
        """
        existing = self._in_flight.get(cache_key)
        if existing is not None:
            return await asyncio.shield(existing)

        task: asyncio.Task[Any] = asyncio.create_task(factory())
        self._in_flight[cache_key] = task
        try:
            return await asyncio.shield(task)
        finally:
            if self._in_flight.get(cache_key) is task:
                del self._in_flight[cache_key]

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

@dataclass
class FillBudget:
    """The ``fill`` bucket: filling the cache is a cost, serving it is not (§16.8).

    Separate from the serve path on purpose. They are different operations and
    must not share a budget, or a burst of cache *hits* could starve a real
    generation.
    """

    capacity: int
    refill_per_min: int
    tokens: float = 0.0
    updated: float = 0.0

    def take(self, *, now: float) -> bool:
        if self.updated == 0.0:
            self.tokens = float(self.capacity)
            self.updated = now
        elapsed = max(0.0, now - self.updated)
        self.tokens = min(float(self.capacity), self.tokens + elapsed * (self.refill_per_min / 60))
        self.updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def new_cache_row_id() -> str:
    return new_id()
