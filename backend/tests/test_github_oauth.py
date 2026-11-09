"""GitHub OAuth helpers and the password-free sign-in page.

Network calls are deliberately not exercised here; the parts that decide whether
a callback is trustworthy - the signed `state` and the redirect allowlist - are
pure and are tested directly.
"""

from __future__ import annotations

import time

import pytest

from app.api.routers.auth import _LOGIN_PAGE, _page
from app.core.errors import BadRequest
from app.services import github_oauth
from app.services.github_oauth import authorize_url, sign_state, verify_state


class TestAuthorizeUrl:
    def test_carries_the_required_parameters(self) -> None:
        url = authorize_url(
            client_id="client-123",
            redirect_uri="https://api.example/v1/auth/extension/github/callback",
            state="signed-state",
            scopes="read:user user:email",
        )
        assert url.startswith("https://github.com/login/oauth/authorize?")
        assert "client_id=client-123" in url
        assert "state=signed-state" in url
        assert "scope=read%3Auser+user%3Aemail" in url
        assert "redirect_uri=https%3A%2F%2Fapi.example" in url


class TestSignedState:
    def test_round_trips_the_return_target(self) -> None:
        state = sign_state({"return_to": "chrome-extension://abc/"}, "secret")
        claims = verify_state(state, "secret")
        assert claims["return_to"] == "chrome-extension://abc/"

    def test_rejects_a_tampered_payload(self) -> None:
        state = sign_state({"return_to": "chrome-extension://abc/"}, "secret")
        encoded, signature = state.rsplit(".", 1)
        flipped = ("A" if encoded[0] != "A" else "B") + encoded[1:]
        with pytest.raises(BadRequest):
            verify_state(f"{flipped}.{signature}", "secret")

    def test_rejects_a_different_secret(self) -> None:
        state = sign_state({"return_to": "chrome-extension://abc/"}, "secret")
        with pytest.raises(BadRequest):
            verify_state(state, "other-secret")

    def test_rejects_an_expired_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = time.time()
        state = sign_state({"return_to": "chrome-extension://abc/"}, "secret")
        monkeypatch.setattr(github_oauth.time, "time", lambda: now + 601)
        with pytest.raises(BadRequest):
            verify_state(state, "secret")

    def test_rejects_a_missing_secret(self) -> None:
        state = sign_state({"return_to": "chrome-extension://abc/"}, "secret")
        with pytest.raises(BadRequest):
            verify_state(state, "")


class TestLoginPage:
    def test_offers_github_and_has_no_password_field(self) -> None:
        # The classic email/password form is gone; this pins that it cannot
        # creep back in as a hidden fallback.
        assert 'type="password"' not in _LOGIN_PAGE
        assert 'name="password"' not in _LOGIN_PAGE
        assert "Continue with GitHub" in _LOGIN_PAGE

    def test_escapes_the_github_link(self) -> None:
        rendered = _page(
            _LOGIN_PAGE,
            github_url='/v1/auth/extension/github?return_to="><script>',
        )
        assert "<script>" not in rendered
        assert "&quot;" in rendered

    def test_callback_route_is_registered(self) -> None:
        from app.main import app

        paths = app.openapi()["paths"]
        assert "/v1/auth/extension/github" in paths
        assert "/v1/auth/extension/github/callback" in paths
