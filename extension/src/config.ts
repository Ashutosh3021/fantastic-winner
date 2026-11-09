/**
 * Build-time configuration.
 *
 * `VITE_*` values are inlined by Vite at build time, so a staged build can
 * point at a different backend without a code change. Nothing secret lives
 * here — the AI keys are backend-only (§18.1, ADR-1).
 */

function required(name: string, fallback: string): string {
  const value = (import.meta.env as Record<string, string | undefined>)[name];
  return (value && value.trim().length > 0 ? value : fallback).replace(/\/+$/, "");
}

export const CONFIG = {
  apiBaseUrl: required("VITE_API_BASE_URL", "https://api.codementor.example"),
  /** §5.7: wall-clock ceiling for any single client request. */
  requestTimeoutMs: 45_000,
  /** §16.2: at most 2 attempts, ever. The second reuses the idempotency key. */
  maxAttempts: 2,
  /** §12.7: auto-advance interval for diagram frames. */
  frameAdvanceMs: 1_500,
} as const;

export const API_PREFIX = "/v1";
export const CLIENT_VERSION = "0.1.0";