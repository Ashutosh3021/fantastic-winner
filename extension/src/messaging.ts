/**
 * Typed content-script ↔ service-worker protocol (§5.7).
 *
 * The content script never calls the backend and never sees a token. It sends
 * a route id and gets back a typed result.
 */

import type { ApiError } from "./schemas";
import type { ResponseOf, RouteId } from "./api/routes";

export type ApiMessage = {
  t: "api";
  route: RouteId;
  params?: Record<string, string>;
  body?: unknown;
  idempotencyKey?: string;
  noCache?: boolean;
};

export type AuthMessage =
  | { t: "auth.login"; provider: string }
  | { t: "auth.logout" }
  | { t: "auth.state" };

export type LogMessage = { t: "log"; level: "info" | "warn" | "error"; msg: string };

export type UiMessage = { t: "ui.open" };

export type Msg = ApiMessage | AuthMessage | LogMessage | UiMessage;

export type ResMeta = {
  cached: boolean;
  fromLocalCache: boolean;
  cacheKey?: string;
  contentVersion?: string;
  creditsRemaining?: number;
  creditsResetAt?: string;
  creditCost?: number;
  prefsVersion?: number;
};

export type Res<T> =
  | { ok: true; data: T; meta: ResMeta }
  | { ok: false; error: ApiError };

export type AuthState = {
  signedIn: boolean;
  email: string | null;
  emailVerified: boolean;
};

/** Maps a message to the payload the service worker sends back. */
export type PayloadOf<M> = M extends { t: "api"; route: infer R extends RouteId }
  ? ResponseOf<R>
  : M extends { t: "auth.login" }
    ? AuthState
    : M extends { t: "auth.logout" }
      ? null
      : M extends { t: "auth.state" }
        ? AuthState
        : null;

export type ResFor<M extends Msg> = Res<PayloadOf<M>>;