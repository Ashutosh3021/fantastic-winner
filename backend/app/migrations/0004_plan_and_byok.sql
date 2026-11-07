-- Plan tier and bring-your-own-key credentials.
--
-- `plan_tier` lives on our application-side user mirror because PyroCore's own
-- `users` table is auth-only. The column is named `plan_tier` rather than
-- `tier` because `tier` already means model routing in the gateway.
--
-- 0 = free (credits apply), 1 = own-key unlimited (manual upgrade only).
ALTER TABLE cm_users ADD COLUMN plan_tier INTEGER NOT NULL DEFAULT 0
  CHECK (plan_tier IN (0, 1));

-- One active own key per user. Kept out of `cm_users` so secrets, timestamps
-- and rotation are isolated from the profile row.
--
-- The ciphertext is a Fernet token; `key_hint` is the last four characters and
-- is for display only. Raw keys are never stored, logged or returned.
CREATE TABLE IF NOT EXISTS user_ai_credentials (
  user_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('openai', 'anthropic', 'gemini')),
  key_ciphertext TEXT NOT NULL,
  key_hint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Which budget paid for an AI call. Rows funded by a learner's own key must not
-- count against our daily spend cap or the per-user token budget.
ALTER TABLE ai_spend ADD COLUMN funded_by TEXT NOT NULL DEFAULT 'codementor';

CREATE INDEX IF NOT EXISTS ai_spend_funded_by_created
  ON ai_spend(funded_by, created_at);
