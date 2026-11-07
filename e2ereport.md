# CodeMentor Test / E2E Readiness Report

**Date:** 2026-11-07  
**Repository:** `C:\Users\ashut\Downloads\fantastic-winner`  
**Status:** **PASS for implemented suites, including browser E2E against a fake API**  
**Not verified:** live Pyronites/AI backend and hosted sign-in

## Summary

| Area | Command | Result | Duration |
|---|---|---|---|
| Backend unit/integration | `.venv\Scripts\python -m pytest -q` | **187 passed** | 7.64s |
| Extension unit | `npm test` | **58 passed** | 18.47s |
| Extension type check | `npm run compile` | **Passed** | - |
| Extension production build | `npm run test:e2e` (build step) | **Passed** | ~64s |
| Backend lint | `python -m ruff check app tests scripts` | **Passed** | - |
| Browser E2E | `npm run test:e2e` | **1 passed** | 6.9s test / 9.5s suite |

**Totals:** 246 automated tests passed, 0 failed, 0 skipped. The E2E path uses a real
Chromium persistent context with the unpacked MV3 extension, but a stateful fake API
instead of a live backend.

## Environment

- Repository-root `.venv` uses the already-installed Python 3.11.6 packages; no pip download.
- Node 24.19.0, npm 12.0.2.
- Extension dependencies installed offline from the local npm cache.
- `@playwright/test@1.59.1` is installed in `extension/`.
- Playwright expects Chromium revision 1217, but this machine caches Chromium 1248.
  The E2E harness selects `chromium-1248` explicitly. Override with
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE` if the cache changes.
- `mypy` is not installed. `coverage` 7.16.2 is available.
- No `extension/.env`, no `backend/.env`, no Pyronites key, and no AI provider key.

## Backend Suite

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

**Result:** `187 passed in 7.64s`

| Test module | Tests |
|---|---:|
| `tests/test_analysis_and_progress.py` | 27 |
| `tests/test_answer_checking.py` | 26 |
| `tests/test_auth_redirect.py` | 24 |
| `tests/test_contract_parity.py` | 11 |
| `tests/test_credit_service.py` | 13 |
| `tests/test_gateway_retries.py` | 11 |
| `tests/test_leak_detector.py` | 19 |
| `tests/test_reveal_boundary.py` | 17 |
| `tests/test_sql_encoding.py` | 39 |
| **Total** | **187** |

Coverage includes credit claiming/settling/rollback, reveal and checklist gates,
answer checking, leak detection, auth redirect allowlists, SQL encoding, gateway
retries, and client/server route/idempotency parity.

## Extension Suite

```powershell
cd extension
npm test
```

**Result:** `4 files passed, 58 tests passed in 18.47s`

| Test file | Tests |
|---|---:|
| `tests/charts-errors.test.ts` | 12 |
| `tests/constraints.test.ts` | 17 |
| `tests/diagrams.test.ts` | 17 |
| `tests/html.test.ts` | 12 |
| **Total** | **58** |

## Browser E2E

```powershell
cd extension
npm run test:e2e
```

The harness:

1. Builds the extension with `VITE_API_BASE_URL=http://127.0.0.1:8787`.
2. Starts `tests/e2e/fake-api.mjs`, a stateful HTTP fake matching the extension's
   Zod response schemas.
3. Loads `.output/chrome-mv3` into a persistent Chromium profile.
4. Seeds the WXT `local:auth` item under its Chrome key `auth`.
5. Serves a deterministic Two Sum LeetCode fixture through request interception.

**Assertions covered:**

- Popup loads signed-in state and shows `e2e@example.com`.
- Overlay extracts Two Sum and lists approaches.
- Selecting Brute Force renders its concept card.
- Choosing Hash Map opens a confirmation with cost `3` and `12 remaining`.
- Cancelling keeps Brute Force; confirming switches and resets the plan.
- `/__state` proves `switchCount=1`, `planGenerated=0`, and no stale question.
- Starting questions, reloading, and resuming on the same question works.
- Hint request shows `Hint 1 of 3`.
- Three wrong answers expose `Show me this step`; reveal shows the explanation.
- A correct answer unlocks the checklist.
- Opening analysis reads the editor textarea fallback and renders the fake analysis.

**Result:** `1 passed (6.9s)`.

## Compile and Build

`npm run compile` exits 0 with no diagnostics.

The E2E build succeeds with 25 output files, about 2.10 MB. Known non-blocking
warning: `content.js` (960 kB) and the popup chunk (571 kB) exceed Vite's 500 kB
warning threshold.

A plain `npm run build` without `extension/.env` still fails intentionally:

```text
VITE_API_BASE_URL is still the placeholder. Create extension/.env from .env.example before a production build.
```

This is the H10 fail-loud behavior, not a regression.

## Backend Lint

```powershell
cd backend
..\.venv\Scripts\python.exe -m ruff check app tests scripts
```

**Result:** `All checks passed!`

## C4 Fix Verification

- `ApproachListCard` requires confirmation before replacing an existing plan.
- The dialog shows the server-derived per-question cost and remaining credits.
- Confirm calls the existing switch path; cancel leaves the current plan intact.
- Backend switch resets plan/content/unlock state and persists the new approach.
- E2E explicitly asserts the reset through fake API state.

The UI uses `costPerQuestion` and `creditsLeft`; no new backend quote endpoint was
added because the existing switch contract does not debit separately.

## Not Run / Remaining Gaps

| Item | Status | Reason |
|---|---|---|
| Live backend HTTP smoke | Not run | No `backend/.env`, Pyronites key, or AI key |
| Real auth flow | Not run | Requires hosted-login origin and provider configuration |
| Live AI generation | Not run | No provider key; fake API returns deterministic content |
| `mypy app` | Not run | Not installed |
| Desktop UX backlog | Open | Top-layer overlay, base font size, keyboard shortcuts |
| Optional cleanup | Open | Unused `noCache` compatibility path |

## Artifacts

- `.venv/` - Python environment
- `extension/node_modules/` - offline install
- `extension/.wxt/` - generated WXT types
- `extension/.output/chrome-mv3/` - E2E production build
- `extension/tests/e2e/` - fake API, fixture, harness, spec, build/run scripts
- `extension/playwright.config.ts`
- On failure: `extension/test-results/` and `extension/playwright-report/` (ignored by git)

## Conclusion

All implemented suites are green: **246 tests passed, 0 failed**. The core learner
flow now works end to end in a real Chromium extension session against a controlled
fake backend, including approach-switch confirmation and reset, reload/resume,
hints, reveal, checklist unlock, and analysis.

The checkout is still not fully bootable against the real product because it has no
Pyronites credentials, AI provider key, or hosted-login configuration. Those remain
environment blockers, not code-test failures.
