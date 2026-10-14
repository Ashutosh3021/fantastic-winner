/**
 * Funnel events (§22.4).
 *
 * Batched, queued in memory, flushed on a timer and on demand. Every batch
 * carries one `Idempotency-Key`, because a retried request must never
 * double-count a learner (PLAN §12).
 */

import { api, newIdempotencyKey } from "./state/client";
import type { EventName } from "./api/routes";

type QueuedEvent = { name: EventName; props: Record<string, unknown> };

const MAX_BATCH = 50;
const FLUSH_MS = 4_000;

let queue: QueuedEvent[] = [];
let timer: ReturnType<typeof setTimeout> | undefined;

function schedule(): void {
  if (timer) return;
  timer = setTimeout(() => {
    timer = undefined;
    void flush();
  }, FLUSH_MS);
}

export function track(name: EventName, props: Record<string, unknown> = {}): void {
  queue.push({ name, props });
  if (queue.length >= MAX_BATCH) {
    void flush();
    return;
  }
  schedule();
}

export async function flush(): Promise<void> {
  if (queue.length === 0) return;
  if (timer) {
    clearTimeout(timer);
    timer = undefined;
  }
  const batch = queue.splice(0, MAX_BATCH);
  try {
    await api("events", {
      body: { events: batch.map((e) => ({ name: e.name, props: e.props })) },
      idempotencyKey: newIdempotencyKey(),
    });
  } catch {
    // Analytics must never block the learner. Drop the batch.
  }
}