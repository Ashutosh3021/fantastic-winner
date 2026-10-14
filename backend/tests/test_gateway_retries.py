"""Datastore retry behaviour.

These cover the condition that killed the first deploy: PyroCore answered 429
during startup and the gateway treated it as fatal, so the container exited and
the whole service went down over a rate limit that clears on its own.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import PyronitesConfig, Settings
from app.core.errors import RateLimited, UpstreamError
from app.repositories.gateway import PyronitesGateway, _retry_after


def _settings(api_key: str = "test-key") -> Settings:
    return Settings(
        pyronites=PyronitesConfig(
            url="http://pyronites.invalid",
            api_key=api_key,
            project_slug="test-project",
            request_timeout_s=5.0,
        )
    )


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestRetryPolicy:
    async def test_rate_limit_is_retried_not_fatal(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 3:
                return httpx.Response(429, headers={"retry-after": "1"})
            return httpx.Response(200, json={"ok": True})

        gw = PyronitesGateway(_settings(), client=_client(handler))
        gw._retry_backoff_s = 0.0  # type: ignore[attr-defined]  # keep the test fast
        response = await gw._request("GET", "http://pyronites.invalid/x")
        assert response.status_code == 200
        assert len(calls) == 3
        await gw.aclose()

    async def test_exhausted_rate_limit_raises_rate_limited(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "1"})

        gw = PyronitesGateway(_settings(), client=_client(handler))
        gw._retry_backoff_s = 0.0  # type: ignore[attr-defined]
        with pytest.raises(RateLimited) as exc:
            await gw._request("GET", "http://pyronites.invalid/x")
        # A 429 must surface as 429, not as a 500: the client can retry it.
        assert exc.value.status == 429
        assert exc.value.retry_after_sec
        await gw.aclose()

    async def test_server_error_is_retried(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 2:
                return httpx.Response(503)
            return httpx.Response(200, json={})

        gw = PyronitesGateway(_settings(), client=_client(handler))
        gw._retry_backoff_s = 0.0  # type: ignore[attr-defined]
        assert (await gw._request("GET", "http://pyronites.invalid/x")).status_code == 200
        await gw.aclose()

    async def test_bad_request_is_not_retried(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(400, json={"detail": "bad sql"})

        gw = PyronitesGateway(_settings(), client=_client(handler))
        with pytest.raises(UpstreamError):
            await gw._request("GET", "http://pyronites.invalid/x")
        assert len(calls) == 1, "a malformed statement will never succeed on retry"
        await gw.aclose()

    async def test_unauthorised_is_not_retried(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(401)

        gw = PyronitesGateway(_settings(), client=_client(handler))
        with pytest.raises(UpstreamError) as exc:
            await gw._request("GET", "http://pyronites.invalid/x")
        assert len(calls) == 1, "a bad key will never start working on retry"
        # The message must name the variables an operator has to change. A bare
        # "401" is what made this cost three deploys to diagnose.
        assert "PYRONITES_KEY" in exc.value.message
        assert "PYRONITES_PROJECT" in exc.value.message
        await gw.aclose()

    async def test_forbidden_also_names_the_variables(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        gw = PyronitesGateway(_settings(), client=_client(handler))
        with pytest.raises(UpstreamError) as exc:
            await gw._request("GET", "http://pyronites.invalid/x")
        assert "PYRONITES_PROJECT" in exc.value.message
        await gw.aclose()

    async def test_transport_error_is_retried(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) < 2:
                raise httpx.ConnectError("cold start")
            return httpx.Response(200, json={})

        gw = PyronitesGateway(_settings(), client=_client(handler))
        gw._retry_backoff_s = 0.0  # type: ignore[attr-defined]
        assert (await gw._request("GET", "http://pyronites.invalid/x")).status_code == 200
        await gw.aclose()


class TestRetryAfterHeader:
    def test_uses_the_header_when_present(self) -> None:
        response = httpx.Response(429, headers={"retry-after": "7"})
        assert _retry_after(response, 1) == 7.0

    def test_falls_back_to_exponential_when_absent(self) -> None:
        assert _retry_after(httpx.Response(429), 1) == 2.0
        assert _retry_after(httpx.Response(429), 3) == 8.0

    def test_never_returns_below_the_floor(self) -> None:
        # A zero or malformed header must not become a hot loop.
        assert _retry_after(httpx.Response(429, headers={"retry-after": "0"}), 1) == 1.0
        assert _retry_after(httpx.Response(429, headers={"retry-after": "soon"}), 1) == 2.0


class TestMissingConfiguration:
    async def test_refuses_to_run_without_a_key(self) -> None:
        # Raised as UpstreamError, not BadRequest: from the API's point of view
        # this is a server misconfiguration, and it should not read as the
        # caller sending something wrong.
        gw = PyronitesGateway(_settings(api_key=""), client=_client(lambda r: httpx.Response(200)))
        with pytest.raises(UpstreamError) as exc:
            await gw._request("GET", "http://pyronites.invalid/x")
        assert "PYRONITES_KEY" in exc.value.message
        await gw.aclose()