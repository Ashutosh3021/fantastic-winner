-- Persisted hint consumption and the simplification level.
--
-- Hints used to be inferred from answer attempts, which only exist after the
-- learner submits. Clicking "Need a hint" twice before answering therefore
-- returned level 1 twice, and a reload forgot the hint entirely. Hint state is
-- now durable per (session, question).
CREATE TABLE IF NOT EXISTS question_hint_state (
  session_id TEXT NOT NULL,
  question_index INTEGER NOT NULL,
  hints_used INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (session_id, question_index)
);

CREATE INDEX IF NOT EXISTS question_hint_state_session
  ON question_hint_state(session_id);

-- The simplify route already reads and writes `simplify_level`, but 0001 never
-- declared the column. Without it the write was rejected by the table API.
ALTER TABLE session_content ADD COLUMN simplify_level INTEGER NOT NULL DEFAULT 0;
