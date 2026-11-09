"""HTTP access to PyroCore.

This is the only module that knows PyroCore exists (§6.1). Everything above it
depends on the repository interfaces, so swapping SQLite for Postgres - or
PyroCore for anything else - is a change to this folder and nowhere else (D7).

Two transports, deliberately chosen:

* **table REST** for ordinary row CRUD. Parameter-bound server-side, so user
  values never pass through SQL text, and it does not trigger PyroCore's
  auto-backup-on-write.
* **SQL execute** for the things the REST surface genuinely cannot do: the
  atomic multi-statement credit claim, conditional updates whose success is
  signalled by row count, and aggregate reads for the progress graphs.

PyroCore backs up the database before every write batch, so the REST path is
also the cheaper one on the hot path; SQL is reserved for where it is required.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx

from ..core.config import Settings
from ..core.errors import BadRequest, NotFound, RateLimited, UpstreamError
from ..core.logging import get_logger
from .sql import safe_identifier


def _retry_after(response: httpx.Response, attempt: int, *, floor: float = 1.0) -> float:
    """How long to wait before retrying a rate-limited request.

    Honours ``Retry-After`` when the upstream sends one, because it knows its own
    window; otherwise backs off exponentially. Never returns less than ``floor``,
    so a zero or malformed header cannot turn into a hot loop against a service
    that is already asking us to slow down.
    """
    header = response.headers.get("retry-after")
    if header:
        try:
            return max(floor, float(int(header)))
        except (TypeError, ValueError):
            pass
    return max(floor, 2.0**attempt)

logger = get_logger(__name__)

# : PyroCore refuses a batch longer than this.
MAX_STATEMENTS = 50

@dataclass(frozen=True)
class SqlResult:
    """One statement's outcome from a PyroCore SQL batch."""

    kind: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    changes: int

    def first(self) -> dict[str, Any] | None:
        if not self.rows:
            return None
        return dict(zip(self.columns, self.rows[0], strict=True))

    def all(self) -> list[dict[str, Any]]:
        return [dict(zip(self.columns, row, strict=True)) for row in self.rows]

@dataclass(frozen=True)
class SqlBatch:
    results: list[SqlResult]

    def first(self) -> dict[str, Any] | None:
        return self.results[0].first() if self.results else None

    def all(self) -> list[dict[str, Any]]:
        return self.results[0].all() if self.results else []

    def changes(self, index: int = 0) -> int:
        return self.results[index].changes if len(self.results) > index else 0

class PyronitesGateway:
    """Thin, typed client for the two PyroCore planes we use."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._max_attempts = 3
        self._retry_backoff_s = 1.5
        self._client = client or httpx.AsyncClient(
            timeout=settings.pyronites.request_timeout_s,
        )

    # -- lifecycle ---

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- plumbing ---

    def _require_config(self) -> None:
        if not self._settings.pyronites.configured:
            raise UpstreamError(
                "The datastore is not configured. Set PYRONITES_URL and PYRONITES_KEY."
            )

    def _scoped(self, path: str) -> str:
        base = self._settings.pyronites.url
        project = self._settings.pyronites.project_slug
        return f"{base}/api/projects/{project}{path}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.pyronites.api_key}"}

    async def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Any = None,
        allow_status: tuple[int, ...] = (),
    ) -> httpx.Response:
        self._require_config()

        # Transient retries. Two conditions resolve themselves and must not fail
        # a request: a cold-starting datastore (tens of seconds, then fine) and a
        # rate limit (429, which by definition means "not now"). Treating 429 as
        # fatal is what previously killed the whole deploy at startup.
        #
        # Only 4xx that mean something *are* returned immediately: a 400 is a bad
        # statement and a 401 is a bad key, and retrying either just burns time.
        last_exc: httpx.HTTPError | None = None
        rate_limited = False
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.request(
                    method, url, headers=self._headers(), json=json_body
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.info(
                    "pyronites %s %s attempt %s failed: %s",
                    method,
                    url.split("/api/projects/")[-1],
                    attempt,
                    type(exc).__name__,
                )
                if attempt < self._max_attempts:
                    await asyncio.sleep(self._retry_backoff_s * attempt)
                continue

            if response.is_success or response.status_code in allow_status:
                return response

            retryable = response.status_code >= 500 or response.status_code == 429
            if not retryable or attempt >= self._max_attempts:
                # Never echo the upstream body to a learner; it may contain SQL.
                logger.warning(
                    "pyronites %s %s -> %s",
                    method,
                    url.split("/api/projects/")[-1],
                    response.status_code,
                )
                if response.status_code == 429:
                    raise RateLimited(
                        "The datastore is busy. Try again shortly.",
                        retry_after_sec=int(_retry_after(response, attempt)),
                    )
                if response.status_code in (401, 403):
                    # Naming the two variables that cause this saves an operator
                    # from reading a bare "401" and guessing. It is nearly always
                    # a key minted against a different project: /auth/me reports
                    # whichever project was touched last, which is not
                    # necessarily the one the app is configured to use.
                    raise UpstreamError(
                        "Datastore rejected the credentials "
                        f"(HTTP {response.status_code}). Check that PYRONITES_KEY is a "
                        f"read/write key minted for project "
                        f"{self._settings.pyronites.project_slug!r}, and that "
                        f"PYRONITES_PROJECT names that same project."
                    )
                raise UpstreamError(f"Datastore returned {response.status_code}")

            if response.status_code == 429:
                rate_limited = True
                wait = _retry_after(response, attempt)
                logger.info(
                    "pyronites %s %s rate limited, waiting %ss before retry %s",
                    method,
                    url.split("/api/projects/")[-1],
                    wait,
                    attempt + 1,
                )
                await asyncio.sleep(wait)
                continue

            logger.info(
                "pyronites %s %s -> %s, retrying",
                method,
                url.split("/api/projects/")[-1],
                response.status_code,
            )
            await asyncio.sleep(self._retry_backoff_s * attempt)

        if rate_limited:
            raise RateLimited(
                "The datastore is busy. Try again shortly.",
                retry_after_sec=int(self._retry_backoff_s * self._max_attempts) + 1,
            )
        raise UpstreamError(
            f"Datastore unreachable: {type(last_exc).__name__ if last_exc else 'unknown'}"
        ) from last_exc

    # -- project-scoped table plane ---

    async def insert_row(self, table: str, data: dict[str, Any]) -> dict[str, Any]:
        response = await self._request("POST", self._scoped(f"/tables/{table}"), json_body=data)
        return _as_dict(response.json())

    async def get_row(self, table: str, row_id: str) -> dict[str, Any] | None:
        response = await self._request(
            "GET", self._scoped(f"/tables/{table}/{row_id}"), allow_status=(404,)
        )
        if response.status_code == 404:
            return None
        return _as_dict(response.json())

    async def update_row(
        self, table: str, row_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        response = await self._request(
            "PATCH", self._scoped(f"/tables/{table}/{row_id}"), json_body=data, allow_status=(404,)
        )
        if response.status_code == 404:
            return None
        return _as_dict(response.json())

    async def delete_row(self, table: str, row_id: str) -> bool:
        response = await self._request(
            "DELETE", self._scoped(f"/tables/{table}/{row_id}"), allow_status=(404,)
        )
        return response.status_code == 200

    async def list_rows(
        self,
        table: str,
        *,
        limit: int = 50,
        offset: int = 0,
        filter_column: str | None = None,
        filter_value: str | None = None,
    ) -> list[dict[str, Any]]:
        """List rows through the parameter-bound REST plane.

        PyroCore supports a single equality filter plus limit/offset here, which
        is enough for the paging the extension asks for. Anything richer goes
        through :meth:`query_all`, which is why that path is reserved.
        """
        self._require_config()
        params: dict[str, Any] = {"limit": max(1, min(limit, 200)), "offset": max(0, offset)}
        if filter_column is not None and filter_value is not None:
            params["filter_column"] = safe_identifier(filter_column)
            params["filter_value"] = str(filter_value)

        try:
            response = await self._client.get(
                self._scoped(f"/tables/{table}"),
                headers=self._headers(),
                params=params,
            )
        except httpx.HTTPError as exc:
            raise UpstreamError(f"Datastore unreachable: {type(exc).__name__}") from exc

        if not response.is_success:
            logger.warning("pyronites list %s -> %s", table, response.status_code)
            raise UpstreamError(f"Datastore returned {response.status_code}")
        payload = response.json()
        return [dict(row) for row in payload] if isinstance(payload, list) else []

    async def table_exists(self, table: str) -> bool:
        response = await self._request("GET", self._scoped("/tables"), allow_status=(404,))
        if response.status_code == 404:
            return False
        names = {str(row.get("name")) for row in response.json()}
        return table in names

    # -- SQL plane ---

    async def execute(self, statements: list[str]) -> SqlBatch:
        """Run statements as one atomic batch.

        PyroCore wraps the whole batch in a single transaction, so a failure
        part-way rolls back everything before it. That property is what the
        credit claim model is built on (§16.5.2).
        """
        if not statements:
            raise BadRequest("No SQL statements provided")
        if len(statements) > MAX_STATEMENTS:
            raise BadRequest(f"Too many statements (max {MAX_STATEMENTS})")

        response = await self._request(
            "POST",
            self._scoped("/sql/execute"),
            json_body={"sql": ";\n".join(statements)},
        )
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise UpstreamError("Datastore returned a non-JSON SQL response") from exc

        results = []
        for raw in payload.get("results", []):
            results.append(
                SqlResult(
                    kind=raw.get("kind", "write"),
                    columns=list(raw.get("columns", [])),
                    rows=[list(row) for row in raw.get("rows", [])],
                    row_count=int(raw.get("row_count", 0)),
                    changes=int(raw.get("changes", 0)),
                )
            )
        return SqlBatch(results=results)

    async def query_one(self, sql: str) -> dict[str, Any] | None:
        return (await self.execute([sql])).first()

    async def query_all(self, sql: str) -> list[dict[str, Any]]:
        return (await self.execute([sql])).all()

    # -- health ---

    async def health(self) -> dict[str, Any]:
        if not self._settings.pyronites.configured:
            return {"database": False, "reason": "not_configured"}
        try:
            response = await self._client.get(
                f"{self._settings.pyronites.url}/health", timeout=5.0
            )
        except httpx.HTTPError as exc:
            return {"database": False, "reason": type(exc).__name__}
        return {"database": response.is_success, "status_code": response.status_code}

def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    raise NotFound("Datastore returned an unexpected shape")