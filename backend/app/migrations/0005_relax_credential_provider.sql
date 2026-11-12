-- Remove the provider whitelist from the credential table.
--
-- 0004 pinned `provider` to the three providers that existed then. A new
-- provider then fails to save with an opaque datastore 400, because the CHECK
-- rejects the row before the application sees it. Provider validation belongs
-- in ByokService.ALLOWED_PROVIDERS, which can change with the code; the table
-- should not need a migration every time a provider is added.
--
-- SQLite cannot drop a CHECK in place, so rebuild the table. The batch runs in
-- one transaction: a failure leaves the original table untouched.
DROP TABLE IF EXISTS user_ai_credentials_v2;

CREATE TABLE user_ai_credentials_v2 (
  user_id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  key_ciphertext TEXT NOT NULL,
  key_hint TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT INTO user_ai_credentials_v2
  (user_id, provider, key_ciphertext, key_hint, created_at, updated_at)
SELECT user_id, provider, key_ciphertext, key_hint, created_at, updated_at
FROM user_ai_credentials;

DROP TABLE user_ai_credentials;

ALTER TABLE user_ai_credentials_v2 RENAME TO user_ai_credentials;
