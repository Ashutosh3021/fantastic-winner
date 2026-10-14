/**
 * Token storage. Only the service worker touches this (§5.6); content scripts
 * never receive a token.
 *
 * Access tokens are short-lived and the refresh token is revoked on logout.
 * `chrome.storage.local` is not encrypted at rest, which is why the access token
 * lifetime is the primary exposure window rather than the stored copy.
 */

import { storage } from "wxt/utils/storage";

export type AuthTokens = {
  accessToken: string;
  refreshToken: string | null;
  /** Epoch ms. */
  expiresAt: number | null;
};

const EMPTY: AuthTokens = { accessToken: "", refreshToken: null, expiresAt: null };

export const authStore = storage.defineItem<AuthTokens>("local:auth", {
  fallback: EMPTY,
  version: 1,
});

/** Refresh a little before real expiry so a request never races the clock. */
const EXPIRY_SKEW_MS = 60_000;

export async function getTokens(): Promise<AuthTokens> {
  return authStore.getValue();
}

export async function getAccessToken(): Promise<string | null> {
  const tokens = await getTokens();
  return tokens.accessToken || null;
}

export async function setTokens(next: AuthTokens): Promise<void> {
  await authStore.setValue(next);
}

export async function clearTokens(): Promise<void> {
  await authStore.setValue(EMPTY);
}

export function isExpired(tokens: AuthTokens, now = Date.now()): boolean {
  if (!tokens.accessToken) return true;
  if (tokens.expiresAt === null) return false;
  return tokens.expiresAt - EXPIRY_SKEW_MS <= now;
}

export function expiresInMs(tokens: AuthTokens, now = Date.now()): number {
  if (tokens.expiresAt === null) return Number.POSITIVE_INFINITY;
  return Math.max(0, tokens.expiresAt - now);
}