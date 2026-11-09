"""Repositories: the only code that talks to the datastore (§6.1).

Services depend on the methods here, never on PyroCore's HTTP shape. Moving to
Postgres - or to anything else - is a change to this folder and the migration
files, and nothing above has to change (D7, §17.4).

Two things worth stating plainly:

* Every write path used on a hot request goes through the parameter-bound table
  REST plane, not SQL text.
* The credit claim model (§16.5.2) is the one place SQL is required, because it
  needs a conditional update whose success is signalled by the affected row
  count, and a multi-statement atomic batch. PyroCore's ``/sql/execute`` gives
  exactly that: one transaction, and ``changes`` per statement.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.errors import Conflict, NotFound, UpstreamError
from ..core.logging import get_logger
from .gateway import PyronitesGateway
from .sql import encode, encode_json, safe_identifier

logger = get_logger(__name__)

def new_id() -> str:
    return str(uuid.uuid4())

def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def _row(value: Any) -> dict[str, Any]:
    """Normalise a PyroCore row into plain Python types."""
    if not isinstance(value, dict):
        return {}
    out: dict[str, Any] = {}
    for key, item in value.items():
        out[key] = json.loads(item) if isinstance(item, str) and item[:1] in "[{" else item
    return out

class BaseRepository:
    table = ""

    def __init__(self, gateway: PyronitesGateway) -> None:
        self.gw = gateway
        safe_identifier(self.table)

    async def insert(self, data: dict[str, Any], *, row_id: str | None = None) -> str:
        row = dict(data)
        row.setdefault("id", row_id or new_id())
        row.setdefault("created_at", now_iso())
        await self.gw.insert_row(self.table, row)
        return str(row["id"])

    async def get(self, row_id: str) -> dict[str, Any] | None:
        found = await self.gw.get_row(self.table, row_id)
        return _row(found) if found else None

    async def require(self, row_id: str) -> dict[str, Any]:
        found = await self.get(row_id)
        if found is None:
            raise NotFound(f"{self.table} row not found")
        return found

    async def update(self, row_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        patch = {key: value for key, value in data.items() if value is not None}
        if not patch:
            return await self.get(row_id)
        updated = await self.gw.update_row(self.table, row_id, patch)
        return _row(updated) if updated else None

    async def delete(self, row_id: str) -> bool:
        return await self.gw.delete_row(self.table, row_id)

    async def where(
        self,
        *,
        column: str,
        value: Any,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        safe_identifier(column)
        rows = await self.gw.list_rows(
            self.table, limit=limit, filter_column=column, filter_value=str(value)
        )
        return [_row(item) for item in rows]

# -- users and preferences ---

class UserRepository(BaseRepository):
    table = "cm_users"

    async def by_pyrocore_id(self, pyrocore_user_id: str) -> dict[str, Any] | None:
        rows = await self.where(column="pyrocore_user_id", value=pyrocore_user_id, limit=5)
        return rows[0] if rows else None

    async def by_email(self, email: str) -> dict[str, Any] | None:
        rows = await self.where(column="email", value=email.lower(), limit=5)
        return rows[0] if rows else None

    async def ensure(
        self, *, pyrocore_user_id: str, email: str, auto_verify: bool
    ) -> tuple[dict[str, Any], bool]:
        """Return ``(user, created)``.

        ``cm_users.id`` is our own id; PyroCore's user id is kept separately
        because PyroCore's ``users`` table is auth-only and deliberately carries
        no application columns.
        """
        existing = await self.by_pyrocore_id(pyrocore_user_id) or await self.by_email(email)
        if existing:
            if auto_verify and not existing.get("email_verified_at"):
                existing = (
                    await self.update(str(existing["id"]), {"email_verified_at": now_iso()})
                    or existing
                )
            return existing, False

        payload = {
            "pyrocore_user_id": pyrocore_user_id,
            "email": email.lower(),
            "email_verified_at": now_iso() if auto_verify else None,
            "updated_at": now_iso(),
        }
        created_id = await self.insert(payload)
        await PreferencesRepository(self.gw).ensure(created_id)
        return {**payload, "id": created_id}, True

class UserAICredentialRepository(BaseRepository):
    """One encrypted own key per user.

    Kept in its own table so a profile read never pulls a secret, and so key
    rotation has its own timestamps. The primary key is ``user_id`` (there is no
    separate ``id``), so the generic row helpers do not apply here.
    """

    table = "user_ai_credentials"

    async def for_user(self, user_id: str) -> dict[str, Any] | None:
        row = await self.gw.query_one(
            f"SELECT * FROM {safe_identifier(self.table)} "
            f"WHERE user_id = {encode(user_id)}"
        )
        return _row(row) if row else None

    async def upsert(
        self,
        *,
        user_id: str,
        provider: str,
        ciphertext: str,
        hint: str,
    ) -> dict[str, Any]:
        existing = await self.for_user(user_id)
        now = now_iso()
        if existing:
            await self.gw.execute(
                [
                    f"UPDATE {safe_identifier(self.table)} SET "
                    f"provider = {encode(provider)}, "
                    f"key_ciphertext = {encode(ciphertext)}, "
                    f"key_hint = {encode(hint)}, "
                    f"updated_at = {encode(now)} "
                    f"WHERE user_id = {encode(user_id)}"
                ]
            )
            return {
                **existing,
                "provider": provider,
                "key_ciphertext": ciphertext,
                "key_hint": hint,
                "updated_at": now,
            }

        await self.gw.execute(
            [
                f"INSERT INTO {safe_identifier(self.table)} "
                "(user_id, provider, key_ciphertext, key_hint, created_at, updated_at) "
                f"VALUES ({encode(user_id)}, {encode(provider)}, {encode(ciphertext)}, "
                f"{encode(hint)}, {encode(now)}, {encode(now)})"
            ]
        )
        return {
            "user_id": user_id,
            "provider": provider,
            "key_ciphertext": ciphertext,
            "key_hint": hint,
            "created_at": now,
            "updated_at": now,
        }

    async def delete_for_user(self, user_id: str) -> bool:
        batch = await self.gw.execute(
            [
                f"DELETE FROM {safe_identifier(self.table)} "
                f"WHERE user_id = {encode(user_id)}"
            ]
        )
        return batch.changes() > 0

class PreferencesRepository(BaseRepository):
    table = "user_preferences"

    async def _find(self, user_id: str) -> dict[str, Any] | None:
        """Read by filter, never by row id.

        This table is keyed by ``user_id``; PyroCore's row endpoints assume an
        ``id`` column, so a GET/PATCH on the primary key can answer 500 - even
        for a row that does not exist yet, which used to abort first sign-in.
        """
        rows = await self.where(column="user_id", value=user_id, limit=1)
        return rows[0] if rows else None

    async def ensure(self, user_id: str) -> None:
        if await self._find(user_id):
            return
        try:
            await self.gw.insert_row(
                self.table,
                {
                    "user_id": user_id,
                    "language": "en",
                    "difficulty_mode": "beginner",
                    "theme": "system",
                    "timezone": "UTC",
                    "prefs_version": 1,
                    "updated_at": now_iso(),
                },
            )
        except UpstreamError:
            # Another request created it between our read and write.
            return

    async def for_user(self, user_id: str) -> dict[str, Any]:
        await self.ensure(user_id)
        found = await self._find(user_id)
        if found is None:
            raise NotFound("preferences not found")
        return found

    async def patch(self, user_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = await self.for_user(user_id)
        merged = {**current, **{k: v for k, v in patch.items() if v is not None}}
        merged["prefs_version"] = int(current.get("prefs_version", 1)) + 1
        merged["updated_at"] = now_iso()
        assignments = ", ".join(
            f"{safe_identifier(key)} = {encode(value)}"
            for key, value in merged.items()
            if key != "user_id"
        )
        await self.gw.execute(
            [
                f"UPDATE {safe_identifier(self.table)} SET {assignments} "
                f"WHERE user_id = {encode(user_id)}"
            ]
        )
        return merged

# -- sessions ---

class SessionRepository(BaseRepository):
    table = "problem_sessions"

    async def active_for(self, user_id: str, slug: str) -> dict[str, Any] | None:
        """One active session per (user, problem), enforced by a partial index.

        The index does the work; this lookup just finds it. If two requests race,
        one insert fails on the unique index rather than creating a second
        session, and the caller retries the read.
        """
        candidates = await self.where(column="user_id", value=user_id, limit=200)
        for row in candidates:
            if row.get("slug") == slug and row.get("status") in ("in_progress", "paused"):
                return row
        return None

    async def list_for(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self.where(column="user_id", value=user_id, limit=limit)

    async def count_in_progress(self, user_id: str) -> int:
        rows = await self.where(column="user_id", value=user_id, limit=200)
        return sum(1 for row in rows if row.get("status") == "in_progress")

    async def create(self, *, user_id: str, slug: str, problem: dict[str, Any],
                     approach_id: str, mode: str, language: str) -> dict[str, Any]:
        payload = {
            "user_id": user_id,
            "slug": slug,
            "problem_url": str(problem.get("url", "")),
            "title": str(problem.get("title", "")),
            "selected_approach": approach_id,
            "mode": mode,
            "language": language,
            "status": "in_progress",
            "unlocked_index": 0,
            "question_count": 0,
            "passed_count": 0,
            "content_version": 1,
            "updated_at": now_iso(),
            "last_activity_at": now_iso(),
        }
        try:
            session_id = await self.insert(payload)
        except UpstreamError as exc:
            # The partial unique index fired: someone created it concurrently.
            existing = await self.active_for(user_id, slug)
            if existing:
                return existing
            raise Conflict("Could not create the session") from exc
        return {**payload, "id": session_id}

class SessionContentRepository(BaseRepository):
    table = "session_content"

    async def delete_for_session(self, session_id: str) -> None:
        await self.gw.execute(
            [
                f"DELETE FROM {safe_identifier(self.table)} "
                f"WHERE session_id = {encode(session_id)}"
            ]
        )

    async def current(self, session_id: str) -> dict[str, Any] | None:
        rows = await self.where(column="session_id", value=session_id, limit=50)
        if not rows:
            return None
        return max(rows, key=lambda row: int(row.get("version", 1)))

    async def upsert_version(
        self,
        *,
        session_id: str,
        approach_id: str,
        version: int,
        prompt_version: str,
        content_version: str,
        **fields: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "version": version,
            "approach_id": approach_id,
            "prompt_version": prompt_version,
            "content_version": content_version,
            **fields,
        }
        current = await self.current(session_id)
        if current and int(current.get("version", 1)) == version:
            await self.update(str(current["id"]), payload)
            return {**current, **payload}
        await self.insert(payload)
        return payload

# -- attempts, mistakes ---

class AttemptRepository(BaseRepository):
    table = "micro_question_attempts"

    async def delete_for_session(self, session_id: str) -> None:
        await self.gw.execute(
            [
                f"DELETE FROM {safe_identifier(self.table)} "
                f"WHERE session_id = {encode(session_id)}"
            ]
        )

    async def for_session(self, session_id: str) -> list[dict[str, Any]]:
        rows = await self.where(column="session_id", value=session_id, limit=200)
        return sorted(rows, key=lambda row: (int(row.get("question_index", 0)),
                                             int(row.get("attempt_no", 0))))

    async def attempt_count(self, session_id: str, question_index: int) -> int:
        rows = await self.for_session(session_id)
        return sum(1 for row in rows if int(row.get("question_index", 0)) == question_index)

class HintStateRepository(BaseRepository):
    table = "question_hint_state"

    async def get(self, session_id: str, question_index: int) -> int:
        rows = await self.where(column="session_id", value=session_id, limit=50)
        for row in rows:
            if int(row.get("question_index", 0)) == question_index:
                return min(3, int(row.get("hints_used", 0) or 0))
        return 0

    async def advance(self, session_id: str, question_index: int, *, floor: int = 0) -> int:
        """Record one consumed hint and return the new count (clamped at 3).

        ``floor`` lets an older attempt row's ``hints_used`` seed the state, so a
        learner who used hints before this table existed does not start over.
        """
        current = max(await self.get(session_id, question_index), floor)
        nxt = min(3, current + 1)
        await self.gw.execute(
            [
                f"INSERT INTO {safe_identifier(self.table)} "
                "(session_id, question_index, hints_used, updated_at) VALUES "
                f"({encode(session_id)}, {encode(question_index)}, {encode(nxt)}, "
                f"{encode(now_iso())}) "
                "ON CONFLICT(session_id, question_index) DO UPDATE SET "
                f"hints_used = {encode(nxt)}, updated_at = {encode(now_iso())}"
            ]
        )
        return nxt

    async def delete_for_session(self, session_id: str) -> None:
        await self.gw.execute(
            [
                f"DELETE FROM {safe_identifier(self.table)} "
                f"WHERE session_id = {encode(session_id)}"
            ]
        )

class MistakeRepository(BaseRepository):
    table = "mistakes"

    async def for_user(self, user_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self.where(column="user_id", value=user_id, limit=limit)
        return sorted(rows, key=lambda row: str(row.get("created_at", "")), reverse=True)

# -- saved cards ---

class SavedCardRepository(BaseRepository):
    table = "saved_cards"

    async def for_user(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        return await self.where(column="user_id", value=user_id, limit=limit)

# -- auth tokens ---

class AuthTokenRepository(BaseRepository):
    table = "cm_auth_tokens"

    @staticmethod
    def hash_token(raw: str) -> str:
        """Only the hash is stored, so a datastore dump does not yield tokens."""
        return hashlib.sha256(f"cm-auth:{raw}".encode()).hexdigest()

    async def issue(
        self, *, user_id: str, raw: str, kind: str, ttl_s: int
    ) -> dict[str, Any]:
        return {
            "id": new_id(),
            "user_id": user_id,
            "token_hash": self.hash_token(raw),
            "kind": kind,
            "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_s)).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z"),
            "created_at": now_iso(),
        }

    async def store(self, payload: dict[str, Any]) -> None:
        await self.gw.insert_row(self.table, payload)

    async def lookup(self, raw: str) -> dict[str, Any] | None:
        rows = await self.where(column="token_hash", value=self.hash_token(raw), limit=2)
        for row in rows:
            if row.get("revoked_at"):
                continue
            if str(row.get("expires_at", "")) <= now_iso():
                continue
            return row
        return None

    async def revoke(self, raw: str) -> bool:
        rows = await self.where(column="token_hash", value=self.hash_token(raw), limit=2)
        for row in rows:
            await self.update(str(row["id"]), {"revoked_at": now_iso()})
            return True
        return False

class LoginCodeRepository(BaseRepository):
    table = "cm_login_codes"

    @staticmethod
    def hash_code(raw: str) -> str:
        return hashlib.sha256(f"cm-code:{raw}".encode()).hexdigest()

    async def issue(self, *, user_id: str, raw: str, return_to: str, ttl_s: int) -> None:
        await self.gw.insert_row(
            self.table,
            {
                "code_hash": self.hash_code(raw),
                "user_id": user_id,
                "return_to": return_to[:500],
                "expires_at": (datetime.now(UTC) + timedelta(seconds=ttl_s)).isoformat(
                    timespec="milliseconds"
                ).replace("+00:00", "Z"),
                "created_at": now_iso(),
            },
        )

    async def consume(self, raw: str) -> dict[str, Any] | None:
        code_hash = self.hash_code(raw)
        rows = await self.where(column="code_hash", value=code_hash, limit=2)
        for row in rows:
            if row.get("consumed_at"):
                continue
            if str(row.get("expires_at", "")) <= now_iso():
                continue
            # Conditional UPDATE keeps the code single-use without trusting a
            # PATCH against this table's non-`id` primary key.
            batch = await self.gw.execute(
                [
                    f"UPDATE {safe_identifier(self.table)} "
                    f"SET consumed_at = {encode(now_iso())} "
                    f"WHERE code_hash = {encode(code_hash)} AND consumed_at IS NULL"
                ]
            )
            return row if batch.changes() == 1 else None
        return None

# -- spend and events ---

class SpendRepository(BaseRepository):
    table = "ai_spend"

    async def record(self, **fields: Any) -> None:
        payload = {
            "id": new_id(),
            "request_id": str(fields.get("request_id", "-")),
            "user_id": str(fields.get("user_id", "-")),
            "task_id": str(fields.get("task_id", "-")),
            "prompt_version": str(fields.get("prompt_version", "-")),
            "provider": str(fields.get("provider", "-")),
            "model": str(fields.get("model", "-")),
            "tier": str(fields.get("tier", "-")),
            "tokens_in": int(fields.get("tokens_in", 0)),
            "tokens_out": int(fields.get("tokens_out", 0)),
            "cached": 1 if fields.get("cached") else 0,
            "cost_usd": float(fields.get("cost_usd", 0.0)),
            "outcome": str(fields.get("outcome", "unknown")),
            "duration_ms": int(fields.get("duration_ms", 0)),
            "finish_reason": fields.get("finish_reason"),
            "funded_by": str(fields.get("funded_by") or "codementor"),
            "created_at": now_iso(),
        }
        await self.gw.insert_row(self.table, payload)

    async def spend_since(self, *, since_iso: str) -> tuple[float, int]:
        """Total USD and token count since a timestamp, for the L5 cap."""
        rows = await self.query_since(since_iso)
        cost = sum(float(row.get("cost_usd") or 0.0) for row in rows)
        tokens = sum(
            int(row.get("tokens_in") or 0) + int(row.get("tokens_out") or 0) for row in rows
        )
        return cost, tokens

    async def query_since(self, since_iso: str) -> list[dict[str, Any]]:
        # Own-key spend is the learner's bill, not ours, so it must not feed the
        # L5 daily cap. Rows written before 0004 default to 'codementor'.
        sql = (
            f"SELECT cost_usd, tokens_in, tokens_out FROM {safe_identifier(self.table)} "
            f"WHERE created_at >= {encode(since_iso)} "
            "AND COALESCE(funded_by, 'codementor') <> 'user'"
        )
        return await self.gw.query_all(sql)

    async def tokens_for_user_since(self, *, user_id: str, since_iso: str) -> int:
        sql = (
            f"SELECT tokens_in, tokens_out FROM {safe_identifier(self.table)} "
            f"WHERE user_id = {encode(user_id)} AND created_at >= {encode(since_iso)} "
            "AND COALESCE(funded_by, 'codementor') <> 'user'"
        )
        rows = await self.gw.query_all(sql)
        return sum(int(row["tokens_in"] or 0) + int(row["tokens_out"] or 0) for row in rows)

class EventRepository(BaseRepository):
    table = "events"

    async def record_batch(
        self, *, user_id: str, events: list[dict[str, Any]], idempotency_key: str
    ) -> int:
        """Insert events, ignoring any (key, name) already recorded.

        Idempotency comes from the unique (idempotency_key, name) index, so a
        retried request cannot double-count a learner (§22.4).
        """
        accepted = 0
        for event in events:
            statement = (
                f"INSERT OR IGNORE INTO {safe_identifier(self.table)} "
                "(id, user_id, name, props_json, idempotency_key, created_at) VALUES "
                f"({encode(new_id())}, {encode(user_id)}, "
                f"{encode(str(event.get('name', ''))[:60])}, "
                f"{encode_json(event.get('props') or {})}, {encode(idempotency_key)}, "
                f"{encode(now_iso())})"
            )
            try:
                await self.gw.execute([statement])
                accepted += 1
            except UpstreamError:
                # A constraint failure here means the event already exists; the
                # unique index is doing its job.
                continue
        return accepted

class ContentCacheRepository(BaseRepository):
    """Cross-user generated content (§15.8).

    Reached mostly through :mod:`app.cache.store`, which owns the key derivation
    and eviction. This exists so the table has one named home in the repository
    layer rather than being a string literal scattered through the services.
    """

    table = "content_cache"

    async def get_by_key(self, cache_key: str) -> dict[str, Any] | None:
        row = await self.gw.query_one(
            f"SELECT * FROM {safe_identifier(self.table)} WHERE cache_key = {encode(cache_key)}"
        )
        return _row(row) if row else None

class IpBudgetRepository(BaseRepository):
    table = "ip_ai_budget"

    async def record_call(
        self, *, ip_hash: str, tokens: int, window_s: int
    ) -> dict[str, Any] | None:
        """Increment this window's counters for an IP; returns the new totals.

        Upsert is done with SQL because the REST plane has no
        ``ON CONFLICT ... DO UPDATE``, and this counter is precisely the layer
        that account farming cannot route around (§16.4).
        """
        start = now_iso()
        end = (datetime.now(UTC) + timedelta(seconds=window_s)).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        batch = await self.gw.execute(
            [
                f"INSERT INTO {safe_identifier(self.table)} "
                "(ip_hash, window_start, window_end, ai_calls, ai_tokens) VALUES "
                f"({encode(ip_hash)}, {encode(start)}, {encode(end)}, 1, {encode(int(tokens))}) "
                f"ON CONFLICT(ip_hash, window_start) DO UPDATE SET "
                f"ai_calls = ai_calls + 1, ai_tokens = ai_tokens + {encode(int(tokens))}",
                f"SELECT ai_calls, ai_tokens FROM {safe_identifier(self.table)} "
                f"WHERE ip_hash = {encode(ip_hash)} AND window_start = {encode(start)}",
            ]
        )
        return batch.results[-1].first() if batch.results else None

    async def daily_calls(self, *, ip_hash: str, day_start: str) -> int:
        sql = (
            f"SELECT COALESCE(SUM(ai_calls), 0) AS calls FROM {safe_identifier(self.table)} "
            f"WHERE ip_hash = {encode(ip_hash)} AND window_start >= {encode(day_start)}"
        )
        row = await self.gw.query_one(sql)
        return int(row["calls"]) if row else 0