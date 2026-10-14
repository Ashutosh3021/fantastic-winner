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