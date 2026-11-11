"""Application entrypoint.

Three cross-cutting concerns live here and nowhere else:

* **Error shape.** Every deliberate failure returns
  ``{"error": {"code", "message"}}``. The extension reads ``error.code`` to
  decide whether to retry, refresh a token or give up, so the codes are part of
  the contract, not decoration.
* **Request ids.** A correlation id on every log line and in the response
  headers. Without it, a learner reporting "it failed" gives us nothing to grep.
* **Lifespan.** Migrations run at boot and the projector starts once per process.
"""

from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from .api.deps import API_PREFIX, build_container, set_container
from .api.routers import account, auth, learning, progress
from .core.config import get_settings
from .core.errors import AppError
from .core.logging import configure_logging, get_logger, set_request_id

logger = get_logger(__name__)



@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)

    if not settings.pyronites.configured:
        # Fail loudly at boot. Starting "successfully" without a datastore means
        # every request 500s later, far from the cause.
        raise RuntimeError(
            "PYRONITES_URL and PYRONITES_KEY must be set before the API can start"
        )

    if not settings.auth.allowed_return_origins:
        # Same reasoning as the datastore check above. Without this the API
        # starts, /health is green, and only a real sign-in attempt reveals
        # that every return origin was rejected.
        raise RuntimeError(
            "EXTENSION_RETURN_ORIGINS must list at least one origin "
            "(for example chrome-extension://<extension id>), otherwise the "
            "extension cannot complete sign-in"
        )

    if settings.environment == "production" and not any(
        origin.startswith("chrome-extension://") for origin in settings.auth.allowed_return_origins
    ):
        logger.warning(
            "EXTENSION_RETURN_ORIGINS contains no chrome-extension:// origin; "
            "no browser extension will be able to finish signing in"
        )

    container = build_container(settings)
    app.state.container = container
    set_container(container)
    app.state.trusted_proxy_count = settings.trusted_proxy_count

    try:
        await container.start()
        logger.info("codementor api ready: %s", settings.environment)
        yield
    finally:
        await container.stop()
        set_container(None)
        app.state.container = None


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="CodeMentor API",
        version=settings.client_version,
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # The extension calls from a chrome-extension:// origin, which CORS treats as
    # an opaque origin. Only the configured origins are allowed, and a wildcard
    # is refused outright rather than silently accepted.
    allowed = list(settings.allowed_origins)
    if "*" not in allowed:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Client-Version",
            ],
            max_age=600,
        )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        set_request_id(request_id)
        request.state.request_id = request_id
        started = time.monotonic()

        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers below turn this into a response; log the
            # duration here so a slow failure is visible even when it raises.
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if elapsed_ms > 2_000:
                logger.warning(
                    "slow failing request %s %s after %sms",
                    request.method,
                    request.url.path,
                    elapsed_ms,
                )
            raise

        elapsed_ms = int((time.monotonic() - started) * 1000)
        if elapsed_ms > 2_000:
            # Only slow requests are logged. Logging every request at info would
            # bury the ones worth investigating.
            logger.warning(
                "slow request %s %s -> %s in %sms",
                request.method,
                request.url.path,
                response.status_code,
                elapsed_ms,
            )

        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        """Map a deliberate failure onto the documented error envelope."""
        if exc.status >= 500:
            logger.exception("unhandled app error on %s", request.url.path)
        else:
            logger.info(
                "%s %s -> %s (%s)",
                request.method,
                request.url.path,
                exc.status,
                exc.code,
            )
        return JSONResponse(
            status_code=exc.status, content=exc.body(), headers=exc.response_headers()
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Validation errors are the client's problem, so they are 400 not 422.

        The extension branches on ``error.code``; a bare FastAPI 422 list would be
        a shape it does not understand.
        """
        fields = [
            ".".join(str(p) for p in error.get("loc", ()) if p != "body")
            for error in exc.errors()[:5]
        ]
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "That request was not valid.",
                    "fields": fields,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """Never leak an internal message to a learner.

        The detail goes to the log with the request id; the client gets a stable
        code it can show as "something went wrong" and a request id to quote.
        """
        request_id = getattr(request.state, "request_id", "?")
        logger.exception("unhandled error [request_id=%s] on %s", request_id, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "Something went wrong on our side.",
                    "request_id": request_id,
                }
            },
        )

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, Any]:
        settings = get_settings()
        return {
            "status": "ok",
            "database": bool(settings.pyronites.configured),
            # Whether /account/ai-key can work at all. False here explains a
            # byok_unavailable error without reading the deployment's secrets.
            "byok": bool(settings.byok.configured),
            # Render sets this at build time, so a deploy can be confirmed from
            # outside without guessing from restart timing.
            "revision": (os.environ.get("RENDER_GIT_COMMIT") or "dev")[:7],
        }

    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(account.router, prefix=API_PREFIX)
    app.include_router(learning.router, prefix=API_PREFIX)
    app.include_router(progress.router, prefix=API_PREFIX)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        reload=bool(os.environ.get("RELOAD")),
    )
