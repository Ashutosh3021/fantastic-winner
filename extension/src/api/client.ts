/**
 * The single place that talks to the backend (§5.7, ADR-2).
 *
 * Responsibilities kept here and nowhere else: attaching `Authorization`,
 * minting and reusing idempotency keys, enforcing the 45 s wall-clock ceiling,
 * honouring `Retry-After`, deduplicating in-flight identical requests, and
 * re-validating every payload with Zod so a malformed response becomes a typed
 * `invalid_response` instead of a crash in the overlay.
 */

import type { z } from "zod";
import { API_PREFIX, CLIENT_VERSION, CONFIG } from "../config";
import type { ErrorCode, ResponseMeta } from "../schemas";
import { ApiFailure, fallbackMessage, isRetryable, parseErrorCode, statusToCode } from "./errors";
import { ROUTES, type BodyOf, type ResponseOf, type RouteId } from "./routes";
import { clearTokens, getTokens, isExpired, setTokens, type AuthTokens } from "./auth";
import { prefsVersionStore } from "../state/prefs";
import { readLocal, writeLocal } from "./cache";

export type Envelope<T> = {
  data: T;
  meta: ResponseMeta;
  /** True when the payload came from the extension's local cache, not the network. */
  fromLocalCache: boolean;
};

export type CallOptions<R extends RouteId> = {
  /** Path params substituted into the route template, e.g. `{ id: sessionId }`. */
  params?: Record<string, string>;
  body?: BodyOf<R>;
  /**
   * Stable across retries of the *same user action*. Required by routes marked
   * `idempotent`. Mint one per click, not per attempt.
   */
  idempotencyKey?: string;
  /** Bypass the local cache read. Writes still happen. */
  noCache?: boolean;
  /** Per-route override; defaults to `CONFIG.requestTimeoutMs`. */
  timeoutMs?: number;
  /** Send no `Authorization` header (used by the login exchange). */
  anonymous?: boolean;
};

type RequestShape = {
  method: string;
  path: string;
  class: string;
  body?: z.ZodTypeAny;
  response: z.ZodTypeAny;
  idempotent?: boolean;
  cacheable?: boolean;
};

function routeOf(id: RouteId): RequestShape {
  return ROUTES[id] as unknown as RequestShape;
}

function fillPath(template: string, params?: Record<string, string>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_m, key: string) => {
    const value = params[key];
    if (value === undefined) {
      throw new ApiFailure("bad_request", `Missing route parameter "${key}".`);
    }
    return encodeURIComponent(value);
  });
}

/**
 * Local lookup pointer for the cache. Built only from values the client already
 * knows (route, path params, body, current `prefs_version`) — never from
 * anything the server uses to build a cache key.
 *
 * `prefs_version` is here so a learner who switches language or level does not
 * keep being served the previous language out of the local cache (§5.6). It
 * changes exactly when the server says our cached preferences are stale.
 */
async function pointerFor(
  route: RouteId,
  params?: Record<string, string>,
  body?: unknown,
): Promise<string> {
  const paramsKey = params ? JSON.stringify(Object.entries(params).sort()) : "";
  const bodyKey = body === undefined ? "" : JSON.stringify(body);
  const prefsKey = await prefsVersionStore.getValue();
  return `${route}|${prefsKey}|${paramsKey}|${bodyKey}`;
}

const inFlight = new Map<string, Promise<Envelope<unknown>>>();
let refreshInFlight: Promise<AuthTokens | null> | null = null;

async function refreshAccessToken(): Promise<AuthTokens | null> {
  if (refreshInFlight) return refreshInFlight;

  const current = await getTokens();
  if (!current.refreshToken) return null;

  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${CONFIG.apiBaseUrl}${API_PREFIX}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: current.refreshToken }),
      });
      if (!res.ok) {
        await clearTokens();
        return null;
      }
      const body = (await res.json()) as {
        access_token: string;
        refresh_token?: string;
        expires_in?: number;
      };
      const next: AuthTokens = {
        accessToken: body.access_token,
        refreshToken: body.refresh_token ?? current.refreshToken,
        expiresAt:
          typeof body.expires_in === "number" ? Date.now() + body.expires_in * 1000 : null,
      };
      await setTokens(next);
      return next;
    } catch {
      // A network blip is not a reason to destroy a valid refresh token.
      return current;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

async function accessTokenFor(forceRefresh: boolean): Promise<string | null> {
  const tokens = await getTokens();
  if (!tokens.accessToken) return null;
  if (forceRefresh || isExpired(tokens)) {
    const refreshed = await refreshAccessToken();
    return refreshed?.accessToken ?? null;
  }
  return tokens.accessToken;
}

function parseRetryAfter(header: string | null): number | undefined {
  if (!header) return undefined;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, Math.ceil(seconds));
  const date = Date.parse(header);
  if (Number.isFinite(date)) return Math.max(0, Math.ceil((date - Date.now()) / 1000));
  return undefined;
}

async function toFailure(response: Response): Promise<ApiFailure> {
  const requestId = response.headers.get("X-Request-Id") ?? undefined;
  let code: ErrorCode = statusToCode(response.status);
  let message = "";
  let retryAfterSec = parseRetryAfter(response.headers.get("Retry-After"));
  let resetAt = response.headers.get("X-Credits-Reset") ?? undefined;
  let shortfall: number | undefined;

  try {
    const body: unknown = await response.json();
    const error =
      typeof body === "object" && body !== null && "error" in body
        ? (body as { error: Record<string, unknown> }).error
        : undefined;
    if (error) {
      code = parseErrorCode(error.code);
      if (typeof error.message === "string" && error.message) message = error.message;
      if (typeof error.retry_after_sec === "number") retryAfterSec = error.retry_after_sec;
      if (typeof error.reset_at === "string") resetAt = error.reset_at;
      if (typeof error.shortfall === "number") shortfall = error.shortfall;
    }
  } catch {
    // Non-JSON error body: keep the status-derived code.
  }

  return new ApiFailure(code, message || fallbackMessage(code), {
    status: response.status,
    ...(retryAfterSec !== undefined ? { retryAfterSec } : {}),
    ...(resetAt !== undefined ? { resetAt } : {}),
    ...(shortfall !== undefined ? { shortfall } : {}),
    ...(requestId !== undefined ? { requestId } : {}),
  });
}

async function sendOnce<R extends RouteId>(
  route: R,
  options: CallOptions<R>,
  attempt: number,
): Promise<Envelope<ResponseOf<R>>> {
  const def = routeOf(route);
  const url = `${CONFIG.apiBaseUrl}${API_PREFIX}${fillPath(def.path, options.params)}`;
  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? CONFIG.requestTimeoutMs;
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Client-Version": CLIENT_VERSION,
  };
  if (def.body) headers["Content-Type"] = "application/json";

  if (!options.anonymous) {
    const token = await accessTokenFor(attempt > 0);
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (def.idempotent) {
    if (!options.idempotencyKey) {
      throw new ApiFailure("bad_request", `Route "${route}" requires an idempotency key.`);
    }
    headers["Idempotency-Key"] = options.idempotencyKey;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: def.method,
      headers,
      signal: controller.signal,
      ...(def.body && options.body !== undefined
        ? { body: JSON.stringify(options.body) }
        : {}),
    });
  } catch {
    const timedOut = controller.signal.aborted;
    throw new ApiFailure(
      timedOut ? "timeout" : "network_error",
      timedOut ? `That took longer than ${Math.round(timeoutMs / 1000)} seconds.` : fallbackMessage("network_error"),
    );
  } finally {
    clearTimeout(timer);
  }

  if (response.status === 401 && !options.anonymous) {
    throw new ApiFailure("unauthorized", fallbackMessage("unauthorized"), { status: 401 });
  }
  if (!response.ok) throw await toFailure(response);

  const raw: unknown = await response.json().catch(() => null);
  const envelope =
    typeof raw === "object" && raw !== null && "data" in raw
      ? (raw as { data: unknown; meta?: unknown })
      : { data: raw, meta: undefined };

  const meta: ResponseMeta = {
    cached: false,
    ...(typeof envelope.meta === "object" && envelope.meta !== null
      ? (envelope.meta as ResponseMeta)
      : {}),
  };

  const parsed = def.response.safeParse(envelope.data);
  if (!parsed.success) {
    throw new ApiFailure(
      "invalid_response",
      fallbackMessage("invalid_response"),
      { status: response.status },
    );
  }

  return { data: parsed.data as ResponseOf<R>, meta, fromLocalCache: false };
}

export async function call<R extends RouteId>(
  route: R,
  options: CallOptions<R> = {},
): Promise<Envelope<ResponseOf<R>>> {
  const def = routeOf(route);
  const pointer = await pointerFor(route, options.params, options.body);

  const existing = inFlight.get(pointer);
  if (existing) return existing as Promise<Envelope<ResponseOf<R>>>;

  const run = (async (): Promise<Envelope<ResponseOf<R>>> => {
    if (def.cacheable && !options.noCache) {
      const hit = await readLocal<ResponseOf<R>>(pointer);
      if (hit) {
        return { data: hit.payload, meta: hit.meta, fromLocalCache: true };
      }
    }

    for (let attempt = 0; attempt < CONFIG.maxAttempts; attempt += 1) {
      try {
        const result = await sendOnce(route, options, attempt);
        if (def.cacheable && result.meta.cache_key) {
          await writeLocal(pointer, {
            cacheKey: result.meta.cache_key,
            contentVersion: result.meta.content_version ?? null,
            payload: result.data,
            meta: result.meta,
          });
        }
        return result;
      } catch (cause) {
        const failure =
          cause instanceof ApiFailure
            ? cause
            : new ApiFailure("unknown", fallbackMessage("unknown"));
        if (!isRetryable(failure.code) || attempt === CONFIG.maxAttempts - 1) throw failure;

        // Same idempotency key on the retry — that is what makes it safe (§5.7).
        const waitMs = failure.retryAfterSec
          ? failure.retryAfterSec * 1000
          : Math.min(2_000 * 2 ** attempt, 4_000) * (0.5 + Math.random());
        await new Promise((r) => setTimeout(r, waitMs));
      }
    }
    throw new ApiFailure("unknown", fallbackMessage("unknown"));
  })();

  inFlight.set(pointer, run as Promise<Envelope<unknown>>);
  try {
    return await run;
  } finally {
    if (inFlight.get(pointer) === run) inFlight.delete(pointer);
  }
}