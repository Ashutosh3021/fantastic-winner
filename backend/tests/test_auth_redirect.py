"""The login callback's ``return_to`` guard (§18.1).

This is the highest-severity bug class in the whole auth flow. The callback
redirects to ``return_to`` carrying a one-time sign-in code, so an unchecked
value hands that code to whoever crafted the link. The tests below are mostly
attempts to get past the allowlist.
"""

from __future__ import annotations

import pytest

from app.api.routers.auth import _safe_return_to
from app.core.errors import BadRequest

ALLOWED = ("chrome-extension://abcdefghijklmnop/", "https://app.codementor.example")


class TestAllowedRedirects:
    def test_exact_extension_origin(self) -> None:
        target = "chrome-extension://abcdefghijklmnop/"
        assert _safe_return_to(target, ALLOWED) == target

    def test_exact_web_origin_with_path(self) -> None:
        target = "https://app.codementor.example/welcome"
        assert _safe_return_to(target, ALLOWED) == target

    def test_relative_path_is_allowed(self) -> None:
        # The extension passes chrome.runtime.getURL(""), which may arrive as a
        # path. Only a path can be allowed without a host, never a bare string.
        assert _safe_return_to("/index.html", ALLOWED) == "/index.html"


class TestSignInFlowEndsOnHttps:
    """The flow must never navigate a web page to chrome-extension://.

    Chrome refuses that with ERR_BLOCKED_BY_CLIENT, which presented as "sign-in
    just fails in the browser". The flow therefore ends on the backend's own
    https origin and the extension reads the code out of the tab URL.
    """

    def test_done_route_exists(self) -> None:
        from app.main import app

        assert "/v1/auth/extension/done" in app.openapi()["paths"]

    def test_done_page_is_inert_and_never_references_the_extension_scheme(
        self,
    ) -> None:
        import asyncio

        from app.api.routers.auth import extension_done

        response = asyncio.run(extension_done(code="abcdef123456"))
        body = response.body.decode("utf-8")
        assert "chrome-extension://" not in body
        assert response.status_code == 200

    def test_done_page_escapes_the_code_prefix(self) -> None:
        import asyncio

        from app.api.routers.auth import extension_done

        response = asyncio.run(extension_done(code='<script>alert(1)</script>'))
        assert "<script>" not in response.body.decode("utf-8")

    def test_return_to_is_still_validated_as_an_allowlist(self) -> None:
        # The redirect no longer uses return_to, but it still proves the caller
        # is an extension we recognise, which is what binds a code to one install.
        with pytest.raises(BadRequest):
            _safe_return_to("https://attacker.example/", ALLOWED)


class TestRejectedRedirects:
    @pytest.mark.parametrize(
        "target",
        [
            "https://evil.example/",
            "http://app.codementor.example/",  # wrong scheme
            "https://app.codementor.example.evil.example/",  # suffix attack
            "https://evil.example/?x=app.codementor.example",  # prefix in query
            "https://evil.example/#https://app.codementor.example",
            "javascript:alert(1)",
            "data:text/html,<script>alert(1)</script>",
            "//evil.example/",
            "chrome-extension://evilid/",
        ],
    )
    def test_rejects_anything_not_exactly_allowlisted(self, target: str) -> None:
        with pytest.raises(BadRequest):
            _safe_return_to(target, ALLOWED)

    def test_rejects_a_bare_relative_word(self) -> None:
        # Not a path, so it cannot be a return target.
        with pytest.raises(BadRequest):
            _safe_return_to("welcome", ALLOWED)

    def test_error_message_does_not_echo_the_target(self) -> None:
        with pytest.raises(BadRequest) as exc:
            _safe_return_to("https://evil.example/", ALLOWED)
        assert "evil.example" not in exc.value.message