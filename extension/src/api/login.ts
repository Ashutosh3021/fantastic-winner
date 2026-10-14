import { API_PREFIX, CONFIG } from "../config";
import type { AuthTokens } from "./auth";
import { clearTokens, getTokens, setTokens } from "./auth";
import { clearLocal } from "./cache";
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

async function hostedFlow(): Promise<AuthState> {
  const extensionOrigin = chrome.runtime.getURL("");
  const redirect = await chrome.tabs.create({ url: loginUrl(extensionOrigin), active: true });
  const tabId = redirect.id;
  if (tabId === undefined) throw new ApiFailure("unknown", "Could not open the sign-in page.");

  const finalUrl = await new Promise<string>((resolve, reject) => {
    const onUpdated = (
      updatedTabId: number,
      info: { status?: string; url?: string },
    ) => {
      if (updatedTabId !== tabId || info.status !== "complete" || !info.url) return;
      if (!info.url.startsWith(extensionOrigin)) return;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      resolve(info.url);
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(onUpdated);
      reject(new ApiFailure("unknown", "Sign-in timed out."));
    }, 120_000);
  });

  const code = pickCode(finalUrl);
  await chrome.tabs.remove(tabId).catch(() => undefined);
  if (!code) throw new ApiFailure("unauthorized", "The sign-in page did not return a code.");

  await setTokens(await exchangeCode(code));
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
  await clearTokens();
  await clearLocal();
}

/** Local-only truth so the popup can render before the first network call. */
export async function authState(): Promise<AuthState> {
  const { accessToken } = await getTokens();
  return { signedIn: Boolean(accessToken), email: null, emailVerified: false };
}