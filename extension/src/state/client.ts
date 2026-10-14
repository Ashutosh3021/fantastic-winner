/**
 * Client-side API surface for the content script (§5.7).
 *
 * Everything here goes through `chrome.runtime.sendMessage`, so the overlay
 * never holds a token, never attaches an `Authorization` header, and never
 * constructs a URL.
 */

import { uuid } from "../lib/async";
import type { Msg, Res, ResFor, AuthState } from "../messaging";
import type { BodyOf, ResponseOf, RouteId } from "../api/routes";
import { ApiFailure } from "../api/errors";

type SendOptions<R extends RouteId> = {
  params?: Record<string, string>;
  body?: BodyOf<R>;
  /** Reuse one key across retries of the same user action. */
  idempotencyKey?: string;
  noCache?: boolean;
};

export type ClientResult<T> = {
  data: T;
  meta: Extract<Res<T>, { ok: true }>["meta"];
};

async function send<M extends Msg>(msg: M): Promise<ResFor<M>> {
  const res = (await chrome.runtime.sendMessage(msg)) as ResFor<M> | undefined;
  if (!res) {
    throw new ApiFailure("unknown", "CodeMentor stopped responding. Reload the page.");
  }
  if (!res.ok) {
    const { code, message, retry_after_sec, reset_at, shortfall } = res.error;
    throw new ApiFailure(code, message, {
      ...(retry_after_sec !== undefined ? { retryAfterSec: retry_after_sec } : {}),
      ...(reset_at !== undefined ? { resetAt: reset_at } : {}),
      ...(shortfall !== undefined ? { shortfall } : {}),
    });
  }
  return res;
}

export async function api<R extends RouteId>(
  route: R,
  options: SendOptions<R> = {},
): Promise<ClientResult<ResponseOf<R>>> {
  const msg: Msg = {
    t: "api",
    route,
    ...(options.params ? { params: options.params } : {}),
    ...(options.body !== undefined ? { body: options.body } : {}),
    ...(options.idempotencyKey ? { idempotencyKey: options.idempotencyKey } : {}),
    ...(options.noCache ? { noCache: true } : {}),
  };
  const res = await send(msg);
  if (!res.ok) throw new ApiFailure(res.error.code, res.error.message);
  return { data: res.data as ResponseOf<R>, meta: res.meta };
}

/** Mint one idempotency key per user action, reuse it for any retry. */
export function newIdempotencyKey(): string {
  return uuid();
}

export const auth = {
  login: (provider = "email"): Promise<Res<AuthState>> => send({ t: "auth.login", provider }),
  logout: (): Promise<Res<null>> => send({ t: "auth.logout" }),
  state: (): Promise<Res<AuthState>> => send({ t: "auth.state" }),
};

export function setPrefs(prefs: Record<string, unknown>): Promise<Res<null>> {
  return send({ t: "prefs.set", prefs: prefs as never });
}

export function log(level: "info" | "warn" | "error", msg: string): void {
  void chrome.runtime.sendMessage({ t: "log", level, msg });
}