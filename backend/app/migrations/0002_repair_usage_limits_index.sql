-- Repair: the usage_limits indexes created by 0001.
--
-- 0001 shipped a partial unique index whose predicate called strftime('now').
-- SQLite rejects non-deterministic functions in index predicates, so that
-- statement never took effect and every INSERT into usage_limits failed with
-- "non-deterministic use of strftime() in an index". The credit path could not
-- write at all, which surfaced to learners as ai_unavailable.
--
-- This replaces it with a deterministic unique index on (user_id, window_start).
-- That is the constraint the reserve upsert actually needs:
--
--   INSERT INTO usage_limits (...) ON CONFLICT(user_id, window_start)
--
-- The "one unexpired window per user" rule is enforced in application code by
-- CreditService.ensure_window, which selects for an unexpired row and re-reads
-- after a conflicting insert. An index predicate cannot express "unexpired"
-- without a non-deterministic function, so it is not attempted here.

DROP INDEX IF EXISTS usage_limits_one_active_window;

CREATE UNIQUE INDEX IF NOT EXISTS usage_limits_user_window_start
  ON usage_limits(user_id, window_start);

CREATE INDEX IF NOT EXISTS usage_limits_user_window
  ON usage_limits(user_id, window_end);