# CodeMentor API

A thinking coach for LeetCode problems, as a Chrome extension plus this API.
The extension extracts the problem, shows a concept card, walks the learner
through micro-questions, then gets out of the way so they write the solution
themselves.

This service holds no database of its own. **PyroCore is the datastore**; every
read and write goes over its REST API, and schema changes are applied as raw SQL
through its transaction endpoint.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
.venv/bin/pip install -e ".[dev]"                   # macOS / Linux

cp .env.example .env        # then fill in PYRONITES_URL, PYRONITES_KEY, one AI key
python scripts/migrate.py   # apply the schema
uvicorn app.main:app --reload
```

`GET /health` answers `{"status":"ok","database":true}` once it is up.
Docs are at `/docs` outside production.

The API reads `.env` itself, so `uvicorn app.main:app` works without exporting
anything. Real environment variables always win, which is what makes the same
image safe on Render and Fly.

## Configuration

Every limit is an environment variable; `.env.example` lists all of them with
the value the code actually defaults to. Only three matter to start:

| Variable | Meaning |
|---|---|
| `PYRONITES_URL` | Base URL of the PyroCore instance |
| `PYRONITES_KEY` | API key, scoped to one project |
| `AI_ANTHROPIC_KEY` / `AI_OPENAI_KEY` / `AI_GEMINI_KEY` | At least one, in production |

List variables are comma separated: `EXTENSION_RETURN_ORIGINS=chrome-extension://abc,https://app.example`.

### Three settings that must differ in production

| Variable | Local | Production | Why |
|---|---|---|---|
| `ALLOW_OFFLINE_PROVIDER` | `true` | **`false`** | With no AI key the offline provider returns schema-shaped filler. It looks healthy and teaches nothing. |
| `AUTH_AUTO_VERIFY_DEV` | `true` | **`false`** | Marks every login's email verified, which disables the verified-email gate. |
| `EXTENSION_RETURN_ORIGINS` | placeholder | your real extension origin | The sign-in callback only redirects to an exact origin match. |

`TRUSTED_PROXY_COUNT` should be `1` behind a single proxy (Render, Fly). It is the
depth at which `X-Forwarded-For` is believed; at `0` every user shares one IP
bucket, and at a higher value a client can spoof its way past the per-IP budget.

## Provisioning PyroCore

The backend needs a project, a key, and the schema.

```bash
# 1. Account and project: sign up or log in, then read last_project_id
#    from GET /auth/me.

# 2. Create a key scoped to that project. read + write is enough; admin is not
#    needed at runtime and must not ship in app code.
#    POST /api/projects/{project_id}/api/keys  {"name":"codementor-app",
#                                               "scopes":["read","write"],
#                                               "project_id":"..."}
#    The key is shown once. Write it straight to .env.

# 3. Apply the schema
python scripts/migrate.py

# 4. Prove it end to end: insert, select, child row, uniqueness, delete
python scripts/smoke_pyronites.py
```

`smoke_pyronites.py` is the gate worth running after any deploy. It exits
non-zero on the first failure and leaves no test rows behind.

## Deploying

Migrations are a **separate deploy step**, not a boot step. Two instances
starting at once would race to apply the same DDL.

### Fly.io

```bash
fly launch --no-deploy
fly secrets set PYRONITES_URL=... PYRONITES_PROJECT=... PYRONITES_KEY=... \
               EXTENSION_RETURN_ORIGINS=... AI_ANTHROPIC_KEY=...
fly deploy          # runs "python scripts/migrate.py" as the release command
```

### Render

Push, then connect the blueprint in the dashboard. Set the `sync: false`
variables as dashboard secrets. Then:

```bash
render exec codementor-api python scripts/migrate.py
```

and set `PYRONITES_AUTO_MIGRATE=false` so a later restart cannot re-apply.

### Docker

```bash
docker build -t codementor-api .
docker run --env-file .env -p 8000:8000 codementor-api
```

Single worker by design: the projector polls `projection_queue` in-process, so a
second worker is a second poller on the same queue.

## Architecture notes

**Credits are metered against questions, not requests.** A claim reserves, the
artifact is generated, then it settles at the true cost. A failure rolls the
reservation back in full — a learner is never charged for an error.

**Retry safety is mandatory, not optional.** Every route that spends credits or
writes reveal state requires an `Idempotency-Key`. A learner who double-clicks on
a slow connection gets the same artifact and the same bill.

**Answering is free.** Only generating questions costs credits. Asking for a
hint costs nothing either, because the hint already exists in the question's
generated detail — charging for help would teach the opposite of the point.

**Projections are out of band.** Answer attempts and queue entries are written in
one transaction; XP, levels, streaks and mastery are derived afterwards by the
projector. If the projector is down, answers still work and nothing is lost.

**The client cannot read ahead.** `CurrentQuestion` has no field for the rubric,
`common_wrong` or the step explanation, so that guarantee is a property of the
type rather than a convention someone has to remember.

## Development

```bash
pytest                      # 165 tests, no network, no secrets
ruff check app tests scripts
mypy app                    # strict
```

The suite is worth running before any change to `credit_service`,
`reveal_boundary`, `answer_checking` or `leak_detector`: each encodes a rule that
is invisible in the code and expensive to get wrong. It has already caught a
login-breaking redirect mismatch, a cache key that was identical for every
learner, and an ordering check that marked every correct answer wrong.