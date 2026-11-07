/**
 * Retired local response cache.
 *
 * The backend does not currently emit the `cache_key` / `content_version`
 * metadata this client used to store entries under, so the read path could
 * never validate a hit and the write path never ran. Server-side content
 * caching remains (the generator's cache); this module only clears entries
 * written by older builds on logout.
 */

import { storage } from "wxt/utils/storage";

const INDEX_KEY = "local:cache:index";
const indexStore = storage.defineItem<Record<string, number>>(INDEX_KEY, {
  fallback: {},
  version: 1,
});

function entryStore(pointer: string) {
  return storage.defineItem<unknown | null>(`local:cache:e:${pointer}`, {
    fallback: null,
    version: 1,
  });
}

/** Drop every legacy entry. Called on logout so no payload outlives the session. */
export async function clearLocal(): Promise<void> {
  const index = await indexStore.getValue();
  await Promise.all(Object.keys(index).map((pointer) => entryStore(pointer).removeValue()));
  await indexStore.setValue({});
}
