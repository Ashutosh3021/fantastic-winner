/**
 * Local response cache (§5.6).
 *
 * The client **never computes a cache key**. The server returns `cache_key` and
 * `content_version` on every cacheable response; we store the payload together
 * with those exact values. The index below is keyed by a *local pointer*
 * (route + path params + client-known inputs) purely so a revisit can find the
 * entry without a round trip � it is not a cache key the server would ever
 * agree with, and it cannot collide across users because it never leaves the
 * extension.
 *
 * A revisit therefore costs zero requests until the backend moves
 * `content_version`, at which point the next real call replaces the entry.
 */

import { CONFIG } from "../config";
import type { ResponseMeta } from "../schemas";
import { storage } from "wxt/utils/storage";

export type CacheEntry<T> = {
  /** The server-provided key this payload was stored under. */
  cacheKey: string;
  /** The server-provided content/prompt version at the time of the call. */
  contentVersion: string | null;
  payload: T;
  meta: ResponseMeta;
  storedAt: number;
};

const INDEX_KEY = "local:cache:index";
const indexStore = storage.defineItem<Record<string, number>>(
  INDEX_KEY,
  { fallback: {}, version: 1 },
);

function entryStore(pointer: string) {
  return storage.defineItem<CacheEntry<unknown> | null>(`local:cache:e:${pointer}`, {
    fallback: null,
    version: 1,
  });
}

const CACHE_TTL_MS = CONFIG.localCacheTtlMs;

export async function readLocal<T>(pointer: string): Promise<CacheEntry<T> | null> {
  const index = await indexStore.getValue();
  const storedAt = index[pointer];
  if (storedAt === undefined) return null;

  if (Date.now() - storedAt > CACHE_TTL_MS) {
    await dropLocal(pointer);
    return null;
  }
  const entry = await entryStore(pointer).getValue();
  return entry ? (entry as CacheEntry<T>) : null;
}

export async function writeLocal<T>(
  pointer: string,
  entry: Omit<CacheEntry<T>, "storedAt">,
): Promise<void> {
  const storedAt = Date.now();
  await entryStore(pointer).setValue({ ...entry, storedAt } as CacheEntry<unknown>);
  const index = await indexStore.getValue();
  index[pointer] = storedAt;
  await indexStore.setValue(index);
}

export async function dropLocal(pointer: string): Promise<void> {
  await entryStore(pointer).removeValue();
  const index = await indexStore.getValue();
  if (index[pointer] !== undefined) {
    delete index[pointer];
    await indexStore.setValue(index);
  }
}

/** Drop everything. Called on logout so no payload outlives the session. */
export async function clearLocal(): Promise<void> {
  const index = await indexStore.getValue();
  await Promise.all(Object.keys(index).map((pointer) => entryStore(pointer).removeValue()));
  await indexStore.setValue({});
}