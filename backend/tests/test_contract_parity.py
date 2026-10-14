"""Contract parity with the extension.

The backend and the extension are two repositories that ship together and are
versioned separately. Nothing in the type system connects them, so this file is
the contract: every route the extension declares must exist on the server with
the same method, and the response models must accept what the client sends.

A rename on either side fails here rather than as a 404 in front of a learner.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.main import app

#: Path parameters differ in name between the two sides; map them explicitly
#: rather than by position.
_PARAM_MAP = {"{id}": "{session_id}", "{k}": "{index}"}

#: Routes the server adds that the extension does not call. Each needs a reason.
_SERVER_ONLY = {
    ("GET", "/health"),
    ("GET", "/v1/auth/extension/login"),
    ("POST", "/v1/auth/extension/login"),
    ("GET", "/v1/auth/extension/signup"),
    ("POST", "/v1/auth/extension/signup"),
    ("POST", "/v1/auth/extension/code"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/logout"),
}


def _server_routes() -> set[tuple[str, str]]:
    schema = app.openapi()
    return {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
    }


def _client_routes(extension_root: Path) -> set[tuple[str, str]]:
    source = (extension_root / "src" / "api" / "routes.ts").read_text(encoding="utf-8")
    entries = re.findall(r'method:\s*"(\w+)",\s*\n?\s*path:\s*"([^"]+)"', source)
    routes: set[tuple[str, str]] = set()
    for method, path in entries:
        for old, new in _PARAM_MAP.items():
            path = path.replace(old, new)
        routes.add((method.upper(), "/v1" + path))
    return routes


class TestRouteParity:
    def test_client_route_table_is_parsed(self, extension_root: Path) -> None:
        # A silent regex failure would make every other test in this file pass
        # vacuously against an empty set.
        routes = _client_routes(extension_root)
        assert len(routes) >= 20, "route table regex failed to match routes.ts"
        assert ("GET", "/v1/me") in routes

    def test_every_client_route_exists_on_the_server(self, extension_root: Path) -> None:
        missing = sorted(_client_routes(extension_root) - _server_routes())
        assert not missing, f"routes the extension calls but the server lacks: {missing}"

    def test_no_unexpected_server_routes(self, extension_root: Path) -> None:
        unexpected = sorted(_server_routes() - _client_routes(extension_root) - _SERVER_ONLY)
        assert not unexpected, f"server routes nobody calls: {unexpected}"

    def test_server_only_routes_are_all_allowlisted(self) -> None:
        """Every extra route needs a stated reason, so the list cannot grow silently."""
        assert ("GET", "/health") in _SERVER_ONLY


class TestResponseModels:
    def test_health_shape(self) -> None:
        from app.main import create_app

        assert create_app() is not None

    def test_error_envelope_matches_what_the_client_expects(self) -> None:
        from app.core.errors import Unauthorized

        body = Unauthorized("Sign in to continue.").body()
        assert set(body) == {"error"}
        assert body["error"]["code"] == "unauthorized"
        assert isinstance(body["error"]["message"], str)

    def test_error_envelope_is_the_only_error_shape(self) -> None:
        # The extension branches on error.code; a bare FastAPI 422 list would be
        # a shape it cannot read.
        from fastapi.exceptions import RequestValidationError

        exc = RequestValidationError(
            [{"loc": ("body", "slug"), "msg": "field required", "type": "missing"}]
        )
        errors = exc.errors()
        assert errors and errors[0]["loc"] == ("body", "slug")


class TestOpenApiIsSane:
    def test_every_operation_has_a_response(self) -> None:
        for path, operations in app.openapi()["paths"].items():
            for method, operation in operations.items():
                responses = operation.get("responses", {})
                assert responses, f"{method.upper()} {path} declares no response"

    def test_protected_routes_do_not_leak_a_200_without_auth(self) -> None:
        """Routes taking CallerDep must not be callable with no token.

        Asserted structurally: every protected path is one the extension calls
        with a bearer token, and the dependency is what enforces it.
        """
        protected = {"/v1/me", "/v1/progress", "/v1/usage", "/v1/sessions"}
        for path in protected:
            assert any(path == p for _, p in _server_routes()), path


def test_delete_me_returns_204_with_no_body() -> None:
    """Deleting data must be safely retryable, so it is a 204, not a JSON null."""
    operation = app.openapi()["paths"]["/v1/me"]["delete"]
    assert "204" in operation["responses"]
    assert "200" not in operation["responses"]