/**
 * Service worker (§5.1).
 *
 * MV3 service workers are ephemeral, so nothing here holds state between
 * events: every handler rehydrates from `chrome.storage`, and every request
 * that can spend credits carries an idempotency key minted by the caller.
 */

import { defineBackground } from "wxt/utils/define-background";

import { call, type CallOptions } from "../src/api/client";
import { ApiFailure, fallbackMessage } from "../src/api/errors";
import { completeHostedLogin, completeWithCode, login, logout, authState } from "../src/api/login";
import { uuid } from "../src/lib/async";
import type { Msg, Res, ResMeta } from "../src/messaging";
import type { RouteId } from "../src/api/routes";
import { prefsVersionStore } from "../src/state/prefs";

function toResMeta(meta: {
  cached?: boolean;
  cache_key?: string;
  content_version?: string;
  credits_remaining?: number;
  credits_reset_at?: string;
  credit_cost?: number;
  prefs_version?: number;
}): ResMeta {
  return {
    cached: meta.cached ?? false,
    fromLocalCache: false,
    ...(meta.cache_key !== undefined ? { cacheKey: meta.cache_key } : {}),
    ...(meta.content_version !== undefined ? { contentVersion: meta.content_version } : {}),
    ...(meta.credits_remaining !== undefined ? { creditsRemaining: meta.credits_remaining } : {}),
    ...(meta.credits_reset_at !== undefined ? { creditsResetAt: meta.credits_reset_at } : {}),
    ...(meta.credit_cost !== undefined ? { creditCost: meta.credit_cost } : {}),
    ...(meta.prefs_version !== undefined ? { prefsVersion: meta.prefs_version } : {}),
  };
}

function fail(cause: unknown): Res<never> {
  if (cause instanceof ApiFailure) return { ok: false, error: cause.toApiError() };
  const message = cause instanceof Error ? cause.message : fallbackMessage("unknown");
  return { ok: false, error: { code: "unknown", message } };
}

async function handleApi(msg: Extract<Msg, { t: "api" }>): Promise<Res<unknown>> {
  const options: CallOptions<RouteId> = {};
  if (msg.params) options.params = msg.params;
  if (msg.body !== undefined) options.body = msg.body as never;
  // A key is required by idempotent routes; minting it here (once per call,
  // reused by the retry loop inside `call`) keeps the invariant total.
  options.idempotencyKey = msg.idempotencyKey ?? uuid();
  if (msg.noCache) options.noCache = true;

  const result = await call(msg.route, options);

  if (result.meta.prefs_version !== undefined) {
    await prefsVersionStore.setValue(result.meta.prefs_version);
  }

  return {
    ok: true,
    data: result.data,
    meta: { ...toResMeta(result.meta), fromLocalCache: result.fromLocalCache },
  };
}

export default defineBackground(() => {
  // Top-level, deliberately. MV3 suspends an idle worker after ~30 s; a tab
  // event wakes it and re-runs this module, and only top-level listeners are
  // registered in time to receive that event. Registering this inside the
  // `auth.login` handler (the old behavior) meant it was dead by the time the
  // learner finished authorising on GitHub, so the one-time code was never
  // exchanged and the popup stayed signed out even though the sign-in page said
  // it had succeeded.
  chrome.tabs.onUpdated.addListener((_tabId, info, tab) => {
    // `changeInfo.url` is only set when the URL changed; the third argument
    // still carries the committed URL and is the safer read on the final
    // redirect.
    const url = info.url ?? tab.url;
    if (info.status !== "complete" || !url) return;
    void completeHostedLogin(url).catch((cause) => {
      console.warn("[codementor:auth] could not finish sign-in", cause);
    });
  });

  chrome.runtime.onMessageExternal.addListener((raw: unknown, _sender, sendResponse) => {
    // The done page on the backend origin sends the code here. Declared in
    // `externally_connectable`, so no other web origin can reach this listener.
    const msg = raw as { t?: unknown; code?: unknown } | null | undefined;
    if (!msg || msg.t !== "auth.code" || typeof msg.code !== "string") return false;
    void completeWithCode(msg.code)
      .then((ok) => sendResponse({ ok }))
      .catch((cause) => {
        console.warn("[codementor:auth] external hand-off failed", cause);
        sendResponse({ ok: false });
      });
    // Keeps the message channel open for the async response above.
    return true;
  });

  chrome.runtime.onMessage.addListener((raw: unknown, _sender, sendResponse) => {
    const msg = raw as Msg;
    if (!msg || typeof msg.t !== "string") return false;

    const work = (async (): Promise<Res<unknown>> => {
      switch (msg.t) {
        case "api":
          return handleApi(msg);
        case "auth.login":
          return { ok: true, data: await login(msg.provider), meta: toResMeta({}) };
        case "auth.logout":
          await logout();
          return { ok: true, data: null, meta: toResMeta({}) };
        case "auth.state":
          return { ok: true, data: await authState(), meta: toResMeta({}) };
        case "log":
          console.warn(`[codementor:${msg.level}] ${msg.msg}`);
          return { ok: true, data: null, meta: toResMeta({}) };
      }
    })();

    work.then(sendResponse, (cause) => sendResponse(fail(cause)));
    return true; // keep the message channel open for the async response
  });

  // A worker revival starts with empty in-memory dedupe state; nothing else to
  // rehydrate because every handler reads from chrome.storage on demand.
});