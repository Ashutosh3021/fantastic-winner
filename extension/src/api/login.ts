import { storage } from "wxt/utils/storage";

import { API_PREFIX, CONFIG } from "../config";
import type { AuthTokens } from "./auth";
import { clearTokens, getTokens, setTokens } from "./auth";
import { clearLocal } from "./cache";
import { call } from "./client";
import { ApiFailure } from "./errors";
import type { AuthState } from "../messaging";

/**
 * Login.
 *
 * Two flows, selected at build time by `VITE_AUTH_FLOW`:
 *
 * - `hosted` — the popup opens the backend's login page. The backend returns
 *   to the extension page URL carrying a short-lived `code`; we exchange that
 *   code for tokens with no extra Chrome permission.
 * - `webext` — `chrome.identity.launchWebAuthFlow` against an OAuth provider.
 *   Only this flow needs the `identity` permission, which `wxt.config.ts`
 *   requests conditionally.
 */

const LOGIN_PATH = `${API_PREFIX}/auth/extension/login`;
const CODE_PATH = `${API_PREFIX}/auth/extension/code`;

function loginUrl(returnTo: string): string {
  const url = new URL(CONFIG.apiBaseUrl + LOGIN_PATH);
  url.searchParams.set("return_to", returnTo);
  return url.toString();
}

async function exchangeCode(code: string): Promise<AuthTokens> {
  const res = await fetch(CONFIG.apiBaseUrl + CODE_PATH, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
  if (!res.ok) {
    throw new ApiFailure("unauthorized", "That sign-in link has expired. Try again.");
  }
  const body = (await res.json()) as {
    access_token: string;
    refresh_token?: string;
    expires_in?: number;
  };
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token ?? null,
    expiresAt: typeof body.expires_in === "number" ? Date.now() + body.expires_in * 1000 : null,
  };
}

function pickCode(returnedUrl: string): string | null {
  try {
    const url = new URL(returnedUrl);
    const fromQuery = url.searchParams.get("code");
    if (fromQuery) return fromQuery;
    // Some providers return the code on the fragment.
    const hash = url.hash.startsWith("#") ? new URLSearchParams(url.hash.slice(1)) : null;
    return hash?.get("code") ?? null;
  } catch {
    return null;
  }
}

const DONE_PATH = `${API_PREFIX}/auth/extension/done`;
const DONE_PREFIX = `${CONFIG.apiBaseUrl}${DONE_PATH}`;

/** Last `/me` profile, used only when the network cannot answer. */
const authProfileStore = storage.defineItem<AuthState | null>("local:auth:profile", {
  fallback: null,
  version: 1,
});

/**
 * Codes already traded for tokens.
 *
 * The completion can be reached twice - once by the tab listener and once by the
 * still-running `auth.login` handler - and a login code is single-use, so a
 * second exchange would fail and look like the whole sign-in failed. Persisted
 * because the worker may have been revived for the second event.
 */
const handledCodeStore = storage.defineItem<string | null>("local:auth:handled-code", {
  fallback: null,
  version: 1,
});

let exchangingCode: string | null = null;

/**
 * Finish a hosted sign-in from the tab URL, if that is what this URL is.
 *
 * This is called from a *top-level* `tabs.onUpdated` listener in the service
 * worker, not from the `auth.login` handler. That distinction is the whole fix:
 * opening the sign-in tab closes the popup, and MV3 suspends an idle worker after
 * about 30 seconds, so a listener registered inside the handler is gone long
 * before the learner has typed a password and submitted the form. The top-level
 * listener is re-registered on every worker revival, which is what a tab event
 * does, so the code still gets exchanged whenever the redirect lands.
 */
export async function completeHostedLogin(url: string): Promise<boolean> {
  if (!url.startsWith(DONE_PREFIX)) return false;
  const code = pickCode(url);
  if (!code) return false;
  if (exchangingCode === code) return true;

  exchangingCode = code;
  try {
    if ((await handledCodeStore.getValue()) === code) return true;
    await setTokens(await exchangeCode(code));
    await handledCodeStore.setValue(code);
    return true;
  } finally {
    exchangingCode = null;
  }
}

async function hostedFlow(): Promise<AuthState> {
  const extensionOrigin = chrome.runtime.getURL("");
  const tab = await chrome.tabs.create({ url: loginUrl(extensionOrigin), active: true });
  const tabId = tab.id;
  if (tabId === undefined) throw new ApiFailure("unknown", "Could not open the sign-in page.");

  // Wait for the token store to fill rather than for a tab event in this scope.
  // The exchange itself happens in `completeHostedLogin`, so this can die with
  // the worker without losing the sign-in; the popup simply re-reads the tokens
  // next time it opens. Each storage read is also an extension API call, which
  // keeps the worker alive while this is running.
  const deadline = Date.now() + 120_000;
  let signedIn = false;
  while (Date.now() < deadline) {
    const { accessToken } = await getTokens();
    if (accessToken) {
      signedIn = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  await chrome.tabs.remove(tabId).catch(() => undefined);
  if (!signedIn) throw new ApiFailure("unknown", "Sign-in timed out.");
  return { signedIn: true, email: null, emailVerified: true };
}

async function webExtFlow(): Promise<AuthState> {
  const redirectUrl = CONFIG.oauthRedirectUrl;
  const returnedUrl: string | undefined = await chrome.identity.launchWebAuthFlow({
    url: loginUrl(redirectUrl),
    interactive: true,
  });
  const code = returnedUrl ? pickCode(returnedUrl) : null;
  if (!code) throw new ApiFailure("unauthorized", "Sign-in did not complete.");
  await setTokens(await exchangeCode(code));
  return { signedIn: true, email: null, emailVerified: true };
}

export async function login(provider: string): Promise<AuthState> {
  const flow = CONFIG.authFlow === "webext" ? webExtFlow : hostedFlow;
  void provider; // Provider choice is made on the hosted page.
  return flow();
}

export async function logout(): Promise<void> {
  const { refreshToken } = await getTokens();
  if (refreshToken) {
    // Revoke server-side first, but never let a failed revocation keep the
    // learner signed in locally.
    await call("logout", {
      body: { refresh_token: refreshToken },
      anonymous: true,
    }).catch(() => undefined);
  }
  await clearTokens();
  await clearLocal();
  await authProfileStore.setValue(null);
}

/** Server-backed auth truth, with the last profile as an offline fallback. */
export async function authState(): Promise<AuthState> {
  const { accessToken } = await getTokens();
  if (!accessToken) return { signedIn: false, email: null, emailVerified: false };

  try {
    const res = await call("me");
    const next: AuthState = {
      signedIn: true,
      email: res.data.email || null,
      emailVerified: res.data.email_verified,
    };
    await authProfileStore.setValue(next);
    return next;
  } catch (cause) {
    if (cause instanceof ApiFailure && cause.code === "unauthorized") {
      await clearTokens();
      await authProfileStore.setValue(null);
      return { signedIn: false, email: null, emailVerified: false };
    }
    const cached = await authProfileStore.getValue();
    return cached ?? { signedIn: true, email: null, emailVerified: false };
  }
}