/** RFC 4122 v4 id, used for `Idempotency-Key` values. */
export function uuid(): string {
  return crypto.randomUUID();
}