"""Typed errors and the stable error contract (§16.10).

Every failure a learner can see has a stable ``code``, a human sentence, and a
next step. The UI never renders a stack trace or a raw provider error, so the
message is written for the person who hit it - including the shared-IP case,
which is deliberately not accusatory (§16.4).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

# The stable codes the extension knows how to render (-16.10).
ERROR_CODES = (
    "unauthorized",
    "email_unverified",
    "upgrade_required",
    "rate_limited",
    "ip_budget",
    "credits_exhausted",
    "insufficient_credits",
    "active_session_limit",
    "generation_in_progress",
    "byok_unavailable",
    "usage_guard",
    "question_locked",
    "checklist_locked",
    "ai_busy",
    "ai_unavailable",
    "ai_output_truncated",
    "ai_invalid_output",
    "degraded_mode",
    "bad_request",
    "not_found",
    "conflict",
    "internal_error",
)

# : Codes where the client must not automatically retry - the answer will not
# : change however many times we ask (-16.2).
FINAL_CODES = frozenset(
    {
        "credits_exhausted",
        "insufficient_credits",
        "active_session_limit",
        "checklist_locked",
        "question_locked",
        "email_unverified",
        "upgrade_required",
        "ai_output_truncated",
        "degraded_mode",
        "bad_request",
        "not_found",
    }
)

class AppError(Exception):
    """Base class for every failure this service raises deliberately."""

    code = "internal_error"
    status = 500

    def __init__(
        self,
        message: str,
        *,
        retry_after_sec: int | None = None,
        reset_at: str | None = None,
        shortfall: int | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retry_after_sec = retry_after_sec
        self.reset_at = reset_at
        self.shortfall = shortfall
        self.extra = extra or {}
        self.headers = headers or {}

    def body(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.retry_after_sec is not None:
            error["retry_after_sec"] = self.retry_after_sec
        if self.reset_at is not None:
            error["reset_at"] = self.reset_at
        if self.shortfall is not None:
            error["shortfall"] = self.shortfall
        error.update(self.extra)
        return {"error": error}

    def response_headers(self) -> dict[str, str]:
        headers = dict(self.headers)
        if self.retry_after_sec is not None:
            headers["Retry-After"] = str(self.retry_after_sec)
        if self.reset_at is not None:
            headers["X-Credits-Reset"] = self.reset_at
        return headers

class Unauthorized(AppError):
    code = "unauthorized"
    status = 401

class EmailUnverified(AppError):
    code = "email_unverified"
    status = 402

class UpgradeRequired(AppError):
    code = "upgrade_required"
    status = 426

class RateLimited(AppError):
    code = "rate_limited"
    status = 429

class IpBudgetExceeded(AppError):
    """L1b. Copy is soft and factual: households and campuses share IPs."""

    code = "ip_budget"
    status = 429

class UsageGuard(AppError):
    """L3. Invisible unless hit; friendly when it is."""

    code = "usage_guard"
    status = 429

class CreditsExhausted(AppError):
    code = "credits_exhausted"
    status = 429

class InsufficientCredits(AppError):
    code = "insufficient_credits"
    status = 409

class ActiveSessionLimit(AppError):
    code = "active_session_limit"
    status = 409

class GenerationInProgress(AppError):
    code = "generation_in_progress"
    status = 409

class QuestionLocked(AppError):
    code = "question_locked"
    status = 409

class ChecklistLocked(AppError):
    code = "checklist_locked"
    status = 409

class ByokUnavailable(AppError):
    """The server cannot store or read an own key right now.

    Missing encryption configuration is a deployment mistake, not a learner
    mistake, so the message never blames the learner and never echoes a key.
    """

    code = "byok_unavailable"
    status = 503

class AiBusy(AppError):
    code = "ai_busy"
    status = 503

class AiUnavailable(AppError):
    code = "ai_unavailable"
    status = 503

class AiOutputTruncated(AppError):
    """§15.3. Deterministic: retrying repeats the same truncation."""

    code = "ai_output_truncated"
    status = 422

class AiInvalidOutput(AppError):
    code = "ai_invalid_output"
    status = 422

class DegradedMode(AppError):
    code = "degraded_mode"
    status = 503

class BadRequest(AppError):
    code = "bad_request"
    status = 400

class NotFound(AppError):
    code = "not_found"
    status = 404

class Conflict(AppError):
    code = "conflict"
    status = 409

class UpstreamError(AppError):
    """PyroCore or an AI provider failed. Never surfaced verbatim to a learner."""

    code = "ai_unavailable"
    status = 503

def error_response(exc: AppError, request_id: str | None = None) -> JSONResponse:
    body = exc.body()
    if request_id:
        body["meta"] = {"request_id": request_id}
    return JSONResponse(status_code=exc.status, content=body, headers=exc.response_headers())

def to_http_exception(exc: AppError) -> HTTPException:
    """Adapter for FastAPI's own exception machinery."""
    return HTTPException(status_code=exc.status, detail=exc.body(), headers=exc.response_headers())