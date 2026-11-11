import { z } from "zod";

/** Stable error codes from the backend (§16.10, §21). */
export const ERROR_CODES = [
  "unauthorized",
  "email_unverified",
  "upgrade_required",
  "rate_limited",
  "ip_budget",
  "credits_exhausted",
  "insufficient_credits",
  "active_session_limit",
  "generation_in_progress",
  "usage_guard",
  "question_locked",
  "checklist_locked",
  "ai_busy",
  "ai_unavailable",
  "byok_unavailable",
  "ai_output_truncated",
  "ai_invalid_output",
  "degraded_mode",
  "bad_request",
  "not_found",
  "network_error",
  "timeout",
  "context_invalidated",
  "invalid_response",
  "unknown",
] as const;

export const errorCodeSchema = z.enum(ERROR_CODES);
export type ErrorCode = z.infer<typeof errorCodeSchema>;

export const apiErrorSchema = z.object({
  code: errorCodeSchema,
  message: z.string(),
  retry_after_sec: z.number().int().min(0).optional(),
  reset_at: z.string().optional(),
  route_class: z.string().optional(),
  shortfall: z.number().int().min(0).optional(),
});
export type ApiError = z.infer<typeof apiErrorSchema>;