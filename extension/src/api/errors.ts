import { type ApiError, type ErrorCode, errorCodeSchema } from "../schemas";

export class ApiFailure extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly retryAfterSec?: number;
  readonly resetAt?: string;
  readonly shortfall?: number;
  readonly requestId?: string;

  constructor(
    code: ErrorCode,
    message: string,
    opts: {
      status?: number;
      retryAfterSec?: number;
      resetAt?: string;
      shortfall?: number;
      requestId?: string;
    } = {},
  ) {
    super(message);
    this.name = "ApiFailure";
    this.code = code;
    this.status = opts.status ?? 0;
    this.retryAfterSec = opts.retryAfterSec;
    this.resetAt = opts.resetAt;
    this.shortfall = opts.shortfall;
    this.requestId = opts.requestId;
  }

  toApiError(): ApiError {
    return {
      code: this.code,
      message: this.message,
      ...(this.retryAfterSec !== undefined ? { retry_after_sec: this.retryAfterSec } : {}),
      ...(this.resetAt !== undefined ? { reset_at: this.resetAt } : {}),
      ...(this.shortfall !== undefined ? { shortfall: this.shortfall } : {}),
    };
  }
}

/**
 * Map an HTTP status onto a stable code when the body carries none.
 *
 * Only statuses with an unambiguous meaning appear here. 409 and 422 are
 * deliberately absent: they mean different things depending on the code in the
 * body (`checklist_locked`, `ai_output_truncated`, …), and guessing one from
 * the status alone would be worse than saying `unknown`.
 */
export function statusToCode(status: number): ErrorCode {
  switch (status) {
    case 400:
      return "bad_request";
    case 401:
      return "unauthorized";
    case 403:
      return "email_unverified";
    case 404:
      return "not_found";
    case 426:
      return "upgrade_required";
    case 429:
      return "rate_limited";
    case 503:
      return "ai_unavailable";
    default:
      return "unknown";
  }
}

export function parseErrorCode(value: unknown): ErrorCode {
  const parsed = errorCodeSchema.safeParse(value);
  return parsed.success ? parsed.data : "unknown";
}

/** Human message used when the backend gave us none. */
export function fallbackMessage(code: ErrorCode): string {
  switch (code) {
    case "network_error":
      return "CodeMentor could not reach the server.";
    case "timeout":
      return "That took too long. Check your connection and try again.";
    case "context_invalidated":
      return "CodeMentor was updated. Reload this page to reconnect.";
    case "invalid_response":
      return "The server sent something CodeMentor could not read.";
    case "unauthorized":
      return "Sign in again to continue.";
    case "email_unverified":
      return "Verify your email to use AI features.";
    case "credits_exhausted":
      return "You've used all your question credits for this window.";
    case "insufficient_credits":
      return "You don't have enough question credits for that.";
    case "active_session_limit":
      return "Pause or finish one of your active problems first.";
    case "checklist_locked":
      return "Finish the micro-questions to unlock the checklist.";
    case "question_locked":
      return "Answer the current question first.";
    case "ai_output_truncated":
      return "The answer ran past its length budget. Nothing was charged.";
    case "ai_unavailable":
      return "The mentor is unavailable right now. Nothing was charged.";
    case "byok_unavailable":
      return "This server cannot store a personal key right now.";
    case "ai_busy":
      return "The mentor is busy. Try again in a moment.";
    case "degraded_mode":
      return "The mentor is resting to keep costs down. Saved cards still work.";
    case "upgrade_required":
      return "Update the CodeMentor extension to keep going.";
    case "generation_in_progress":
      return "That is already being generated.";
    default:
      return "Something went wrong.";
  }
}

/**
 * Errors where one automatic retry is safe and useful (§16.2). `ai_busy` and
 * `generation_in_progress` are transient server states; the network codes never
 * reached the backend at all.
 */
export function isRetryable(code: ErrorCode): boolean {
  return (
    code === "ai_busy" ||
    code === "generation_in_progress" ||
    code === "network_error" ||
    code === "timeout"
  );
}

/** Errors that are final: retrying cannot change the outcome (§16.2). */
export function isFinal(code: ErrorCode): boolean {
  return (
    code === "credits_exhausted" ||
    code === "insufficient_credits" ||
    code === "active_session_limit" ||
    code === "checklist_locked" ||
    code === "question_locked" ||
    code === "email_unverified" ||
    code === "upgrade_required" ||
    code === "ai_output_truncated" ||
    code === "degraded_mode"
  );
}