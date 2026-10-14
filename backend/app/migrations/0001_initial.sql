-- CodeMentor schema v1 (ARCHITECTURE.md §17.2).
--
-- Applied through PyroCore's SQL plane, one migration file at a time, inside a
-- single transaction each. Written as plain SQLite DDL: partial unique indexes
-- are load-bearing here (they are what make a credit window race impossible
-- rather than merely unlikely, §17.3), and they need DDL that the REST table
-- API cannot express.
--
-- `id` columns are TEXT holding UUIDs, because PyroCore auto-generates a
-- string id only when `id` is not declared INTEGER.

-- ── users ────────────────────────────────────────────────────────────────
-- PyroCore's own `users` table is auth-only and deliberately has no profile
-- columns, so CodeMentor keeps the application-side mirror it actually needs:
-- the verified-email timestamp that gates AI routes, and account age for the
-- new-account ramp.
CREATE TABLE IF NOT EXISTS cm_users (
  id TEXT PRIMARY KEY,
  pyrocore_user_id TEXT NOT NULL UNIQUE,
  email TEXT NOT NULL UNIQUE,
  email_verified_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id TEXT PRIMARY KEY,
  language TEXT NOT NULL DEFAULT 'en',
  difficulty_mode TEXT NOT NULL DEFAULT 'beginner',
  theme TEXT NOT NULL DEFAULT 'system',
  timezone TEXT NOT NULL DEFAULT 'UTC',
  prefs_version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL
);

-- ── problem sessions ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS problem_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  problem_url TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  selected_approach TEXT NOT NULL,
  mode TEXT NOT NULL,
  language TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'in_progress',
  unlocked_index INTEGER NOT NULL DEFAULT 0,
  question_count INTEGER NOT NULL DEFAULT 0,
  passed_count INTEGER NOT NULL DEFAULT 0,
  content_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_activity_at TEXT NOT NULL
);

-- One active session per (user, problem): switching back to a problem resumes
-- the session you already have rather than silently starting a second one.
CREATE UNIQUE INDEX IF NOT EXISTS problem_sessions_one_active
  ON problem_sessions(user_id, slug)
  WHERE status IN ('in_progress', 'paused');

CREATE INDEX IF NOT EXISTS problem_sessions_user_status
  ON problem_sessions(user_id, status);

-- ── session content ──────────────────────────────────────────────────────
-- The plan *shape* and the per-question *detail* are stored separately. The
-- shape is produced once; detail is filled lazily when a question is first
-- reached (§10.3). Neither is ever returned whole to a client (§10.4).
CREATE TABLE IF NOT EXISTS session_content (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  approach_id TEXT NOT NULL,
  concept_json TEXT,
  diagram_json TEXT,
  plan_shape_json TEXT,
  plan_detail_json TEXT,
  checklist_json TEXT,
  simplify_json TEXT,
  prompt_version TEXT NOT NULL,
  content_version TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (session_id, version)
);

CREATE INDEX IF NOT EXISTS session_content_session ON session_content(session_id, version);

-- ── attempts (append-only) ───────────────────────────────────────────────
-- The single source of truth for every derived statistic about the learner.
-- Nothing below increments a counter; everything is recomputed from here
-- (§19.2, §19.4).
CREATE TABLE IF NOT EXISTS micro_question_attempts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  question_index INTEGER NOT NULL,
  user_answer TEXT NOT NULL DEFAULT '',
  was_correct INTEGER NOT NULL DEFAULT 0,
  verdict TEXT NOT NULL,
  attempt_no INTEGER NOT NULL DEFAULT 1,
  hints_used INTEGER NOT NULL DEFAULT 0,
  time_taken_seconds INTEGER NOT NULL DEFAULT 0,
  mistake_type TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS attempts_session_index
  ON micro_question_attempts(session_id, question_index);

-- ── mistakes ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mistakes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  session_id TEXT,
  concept TEXT NOT NULL,
  mistake_type TEXT NOT NULL,
  short_explanation TEXT NOT NULL DEFAULT '',
  problem_url TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'judge',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS mistakes_user_concept ON mistakes(user_id, concept, created_at);

-- ── credit windows ───────────────────────────────────────────────────────
-- The fast counter. `usage_limits` is never consulted to decide whether to
-- charge; `credit_claims` is (§16.5.1).
CREATE TABLE IF NOT EXISTS usage_limits (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  question_credits_used INTEGER NOT NULL DEFAULT 0,
  question_credits_limit INTEGER NOT NULL DEFAULT 12,
  active_sessions INTEGER NOT NULL DEFAULT 0,
  ai_tokens_used INTEGER NOT NULL DEFAULT 0,
  analyses_used INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- The partial unique index is the fix for a defect the design otherwise had:
-- without it, two concurrent first-spends both see "no active window", both
-- insert, and one row becomes a shadow that is never read again — the learner
-- is charged and shown 12/12. Here the second insert fails loudly (§17.3).
--
-- The predicate uses SQLite's `strftime` because a partial index predicate
-- cannot reference a bind parameter; the expression is constant-folded by
-- SQLite and evaluated per row.
CREATE UNIQUE INDEX IF NOT EXISTS usage_limits_one_active_window
  ON usage_limits(user_id)
  WHERE window_end > strftime('%Y-%m-%dT%H:%M:%fZ', 'now');

CREATE INDEX IF NOT EXISTS usage_limits_user_window ON usage_limits(user_id, window_end);

-- ── credit claims (the idempotency anchor) ───────────────────────────────
-- One row per Idempotency-Key. The INSERT *is* the guard: concurrent identical
-- requests produce exactly one winner and one clean loser that reads the
-- winner's state. There is no read-then-write window, and the AI call cannot be
-- entered twice for the same key (§16.5.1).
CREATE TABLE IF NOT EXISTS credit_claims (
  idempotency_key TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  state TEXT NOT NULL,
  reserved_n INTEGER NOT NULL DEFAULT 0,
  actual_n INTEGER,
  session_id TEXT,
  cached_key TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS credit_claims_user ON credit_claims(user_id, created_at);

-- Append-only audit. Unique on (key, operation) so a retried settle cannot
-- double-append. Never read to decide whether to charge (§16.5.2).
CREATE TABLE IF NOT EXISTS credit_ledger (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  session_id TEXT,
  idempotency_key TEXT NOT NULL,
  operation TEXT NOT NULL,
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (idempotency_key, operation)
);

-- ── content cache ────────────────────────────────────────────────────────
-- Cross-user generated content, keyed by a server-computed hash. Holds no user
-- text. `slug_family` drives the per-slug row cap that bounds cache-key
-- forgery (§15.8).
CREATE TABLE IF NOT EXISTS content_cache (
  cache_key TEXT PRIMARY KEY,
  task_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  content_version TEXT NOT NULL,
  slug_family TEXT NOT NULL,
  approach_id TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT 'en',
  mode TEXT NOT NULL DEFAULT 'beginner',
  payload_json TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  negative INTEGER NOT NULL DEFAULT 0,
  error_code TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS content_cache_expires ON content_cache(expires_at);
CREATE INDEX IF NOT EXISTS content_cache_slug_family ON content_cache(slug_family, created_at);

-- ── cost attribution ─────────────────────────────────────────────────────
-- Written by the gateway on EVERY call, hit or miss, success or failure. This
-- table is what makes cost-per-learner a readable number rather than a guess
-- (§6.2, §22.3).
CREATE TABLE IF NOT EXISTS ai_spend (
  id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  tier TEXT NOT NULL,
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  cached INTEGER NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,
  outcome TEXT NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  finish_reason TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ai_spend_user_created ON ai_spend(user_id, created_at);
CREATE INDEX IF NOT EXISTS ai_spend_task_created ON ai_spend(task_id, created_at);
CREATE INDEX IF NOT EXISTS ai_spend_prompt_version ON ai_spend(prompt_version, created_at);

-- ── per-IP AI budget (L1b) ───────────────────────────────────────────────
-- Separate from the in-process token buckets because this one has to survive a
-- restart on a single-instance deploy, and because it is the layer account
-- farming cannot get around.
CREATE TABLE IF NOT EXISTS ip_ai_budget (
  ip_hash TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  ai_calls INTEGER NOT NULL DEFAULT 0,
  ai_tokens INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (ip_hash, window_start)
);

CREATE INDEX IF NOT EXISTS ip_ai_budget_window ON ip_ai_budget(window_end);

-- ── XP / streaks ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_stats_events (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  event TEXT NOT NULL,
  delta INTEGER NOT NULL,
  ref_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (ref_id)
);

CREATE TABLE IF NOT EXISTS user_stats (
  user_id TEXT PRIMARY KEY,
  xp INTEGER NOT NULL DEFAULT 0,
  level INTEGER NOT NULL DEFAULT 1,
  current_streak INTEGER NOT NULL DEFAULT 0,
  longest_streak INTEGER NOT NULL DEFAULT 0,
  last_active_local_date TEXT,
  updated_at TEXT NOT NULL
);

-- ── projected read models ────────────────────────────────────────────────
-- Written only by the projector, never during a request. If the projector is
-- down, answers still work and nothing is lost — the queue is durable and the
-- state is recomputable from the append-only tables above (§19.4).
CREATE TABLE IF NOT EXISTS concept_progress (
  user_id TEXT NOT NULL,
  concept TEXT NOT NULL,
  practice_count INTEGER NOT NULL DEFAULT 0,
  correct_first_try INTEGER NOT NULL DEFAULT 0,
  hints_total INTEGER NOT NULL DEFAULT 0,
  attempts_total INTEGER NOT NULL DEFAULT 0,
  mastery REAL NOT NULL DEFAULT 0,
  last_practiced_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, concept)
);

CREATE TABLE IF NOT EXISTS review_queue (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  concept TEXT NOT NULL,
  box INTEGER NOT NULL DEFAULT 1,
  review_due_at TEXT NOT NULL,
  priority TEXT NOT NULL DEFAULT 'normal',
  updated_at TEXT NOT NULL,
  UNIQUE (user_id, concept)
);

CREATE INDEX IF NOT EXISTS review_queue_user_due ON review_queue(user_id, review_due_at);

CREATE TABLE IF NOT EXISTS saved_cards (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  slug TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  approach_id TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'concept',
  content_ref TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE (user_id, slug, approach_id, kind)
);

-- ── funnel events ────────────────────────────────────────────────────────
-- Every write is idempotency-keyed, so a retried request cannot double-count a
-- learner (PLAN §12).
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  props_json TEXT NOT NULL DEFAULT '{}',
  idempotency_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (idempotency_key, name)
);

CREATE INDEX IF NOT EXISTS events_user_created ON events(user_id, created_at);

-- ── projector queue ──────────────────────────────────────────────────────
-- Durable, so derived state can be replayed after a crash. `dedupe_key` makes
-- draining idempotent: replaying a batch cannot double-apply an increment.
CREATE TABLE IF NOT EXISTS projection_queue (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  dedupe_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  processed_at TEXT,
  UNIQUE (dedupe_key)
);

CREATE INDEX IF NOT EXISTS projection_queue_pending ON projection_queue(processed_at, created_at);

-- ── extension auth ───────────────────────────────────────────────────────
-- Opaque tokens minted by this service. PyroCore issues httpOnly-cookie
-- sessions, which a Chrome extension cannot use, so the bridge translates once
-- at login and everything after that is a bearer token the worker can hold.
CREATE TABLE IF NOT EXISTS cm_auth_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS cm_auth_tokens_user ON cm_auth_tokens(user_id, kind);

-- One-time login codes handed to the extension during the redirect dance.
CREATE TABLE IF NOT EXISTS cm_login_codes (
  code_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  return_to TEXT NOT NULL DEFAULT '',
  expires_at TEXT NOT NULL,
  consumed_at TEXT,
  created_at TEXT NOT NULL
);

-- ── analysis ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analysis_results (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  editor_language TEXT NOT NULL DEFAULT '',
  result_json TEXT NOT NULL,
  cached INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, code_hash)
);

CREATE INDEX IF NOT EXISTS analysis_results_session ON analysis_results(session_id, created_at);