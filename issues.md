# CodeMentor — Functional & Architecture Gap Review

Reviewed at `HEAD 6edb6f6` (`ship the extension origin as a default so sign-in cannot silently break`).
Scope: extension + backend as they exist in this checkout. No code was changed.

## Bottom line

The backend is mostly coherent. The extension is not wired to it consistently enough to complete its own core flow.

The first hard failure is deterministic: the concept route requires `Idempotency-Key`, and the extension does not send it. That kills the flow immediately after the learner chooses an approach. Even after that is fixed, there is no session rehydration, no real approach switch, no working reveal path, and the hint/reveal UI maps to the wrong backend semantics. Those are not polish problems; they are the difference between “works in a demo” and “works when a learner reloads, retries, or changes their mind.”

## Symptom map

| Observed symptom | Actual cause |
|---|---|
| “Choosing an approach just errors.” | `ROUTES.concept` is missing `idempotent: true`, so the required header is never sent. |
| “It spins forever on a problem.” | `refreshUsage()` is awaited without a catch; any 401/offline failure skips `pending: "none"` and `loadApproaches()`. |
| “Reloading loses everything.” | The learner store is reset on every route change, and the unused `sessionsList` / `sessionGet` routes are the only resume mechanism. |
| “After 3 problems I cannot open any of them.” | The active-session limit is checked before the existing-session lookup, so even a resume is rejected. |
| “Switching approaches changes nothing.” | `switchApproach()` expects a quote; the backend returns a `SessionSummary` and leaves the old plan/content intact. |
| “Hints are always the same.” | Hint requests are not persisted; the backend derives the level only from prior answer attempts. |
| “Show me this step does nothing.” | The UI submits a normal answer with `hints_used: 3`; the backend only releases the step after the attempt cap. |
| “It says my email is unverified after I signed in.” | `auth.state()` always returns `email: null, emailVerified: false`; the popup ignores the `/me` response that actually has the truth. |

## Critical

### C1. The concept route is guaranteed to fail with `400`

- **Where:** `extension/src/api/routes.ts:86-92`, `extension/src/api/client.ts:207-212`, `backend/app/api/routers/learning.py:186`.
- **What:** `concept` is not marked `idempotent: true`. `sendOnce()` only attaches `Idempotency-Key` when that flag is set. The backend calls `require_idempotency_key(caller)` unconditionally and raises `BadRequest` when the header is absent.
- **Impact:** `chooseApproach()` sets `stage: "concept"`, calls `loadConcept()`, and the request fails. `store.concept` stays `null`, so the `stage === "concept" && store.concept` branch never renders. The retry button calls `loadApproaches()`, which does not reset the stage, so the UI can remain trapped in an empty concept stage. This is the primary reason the extension is not functional.
- **Fix:** Mark `concept` idempotent and mint/pass a key, or stop requiring the key on a read-only route. Do not leave the client and server disagreeing about header requirements.

### C2. There is no session rehydration, and reload restarts at question 1

- **Where:** `extension/src/state/learner.ts:192-215`, `extension/entrypoints/content.tsx:101-103`, `extension/src/api/routes.ts:66-77`, `extension/src/state/learner.ts:318-345`, `backend/app/api/routers/learning.py:251-319`.
- **What:** `sessionsList` and `sessionGet` exist in the route table but are never called anywhere in the extension. On every route change the store is reset, then the user is sent through “choose an approach” again. `startQuestions()` calls `POST /micro-questions`. When a plan already exists, that route returns the **first** plan question, not the learner’s current `unlocked_index`. The route that does return the current question, `GET /micro-questions/current`, is unused.
- **Impact:** Reloading a problem loses the visible stage, the current question, hints, feedback, checklist, and analysis. The learner is silently rewound to question 1 while the backend still has their real progress. This makes normal SPA navigation and browser refresh destructive.
- **Fix:** On extraction, look up the active session for the slug (`GET /sessions` or a slug filter), then `GET /sessions/{id}` to restore `unlocked_index`, current question, checklist/analysis unlock state, and the correct stage. Do not create a new session until that lookup misses.

### C3. At the active-session limit, even resuming an existing session is rejected

- **Where:** `backend/app/api/routers/learning.py:93-106`, `backend/app/services/session_service.py:99-126`.
- **What:** `create_session()` counts in-progress sessions and raises `ActiveSessionLimit` before calling `open_session()`. `open_session()` is the function that reuses an existing `(user, slug)` session. With three active sessions, the request is rejected before the reuse path is reached.
- **Impact:** A learner with three open problems cannot resume any of them through the extension. Combined with C2, they are simply locked out of all existing work.
- **Fix:** Resolve the existing session first; only enforce the limit when the insert would actually create a fourth session. The partial unique index already protects the race.

### C4. “Switch approach” does not switch the learning plan

- **Where:** `extension/src/state/learner.ts:257-286`, `extension/src/api/routes.ts:78-84`, `backend/app/api/routers/learning.py:147-166`, `backend/app/services/session_service.py:108-126`.
- **What:** The client treats `PATCH /sessions/{id}` as a cost quote and then calls `loadConcept()`. The backend `patch_session` only writes `selected_approach` and/or `status`; it does not clear the existing plan, checklist, content versions, or progress. The response model is `SessionSummary`, not a quote. The subsequent `startQuestions()` will reuse the existing plan because `bundle.plan` is still present.
- **Impact:** The UI clears the concept locally and says the switch resets progress, but the old micro-questions and checklist remain. The learner gets the new concept and the old plan. Even with C1 fixed, switching is cosmetic.
- **Fix:** Implement an explicit switch contract: quote cost, confirm, reset plan/content/unlock state, persist the new approach, and return the new quote/state. Do not overload a generic PATCH with this behavior.

### C5. `refreshUsage()` failure leaves the overlay stuck in “extracting”

- **Where:** `extension/entrypoints/content.tsx:121-123`, `extension/src/ui/overlay.tsx:434-438`.
- **What:** `onRouteChange()` does `await refreshUsage()` before setting `pending: "none"` and calling `loadApproaches()`. `refreshUsage()` calls `GET /usage`; it rejects on signed-out (401), offline, or backend failure. Nothing catches it in `onRouteChange`. The `.then(watchDescription)` attached at `content.tsx:200` also never runs.
- **Impact:** Signed-out or backend-down users see the extraction skeleton forever, and description re-extraction is never installed. This is the second most common “it just doesn’t work” state.
- **Fix:** Put `refreshUsage()` in its own `try/catch` (or `finally` for `pending`) and always proceed to the approach list. Usage is a display detail, not a prerequisite for extraction.

### C6. A failed concept request leaves no path back to the approach list

- **Where:** `extension/src/state/learner.ts:238-255`, `extension/src/state/learner.ts:217-235`, `extension/src/ui/overlay.tsx:230-232`, `extension/src/ui/overlay.tsx:254-293`.
- **What:** `chooseApproach()` commits `stage: "concept"` before `loadConcept()` succeeds. If `loadConcept()` fails, `concept` is `null`. The approach list only renders in `stage === "idle" || "approaches"`, or in `stage === "concept"` when `store.concept` exists. The error retry calls `loadApproaches()`, which deliberately preserves the current stage unless it is `idle`. The user is left with an error card and no usable card.
- **Impact:** A transient concept failure is unrecoverable without a reload, and a reload triggers C2.
- **Fix:** Only move to `concept` after the concept actually loads, or have the error action restore the previous stage and retry the failed operation.

## High

### H1. Concept reads charge credits and never settle; failures and cache hits still cost

- **Where:** `backend/app/api/routers/learning.py:186-197`, `backend/app/api/routers/learning.py:507-538`, `backend/app/services/credit_service.py:158-276`.
- **What:** `read_concept()` calls `_spend_credit(..., reserve_n=1)` and then returns the card. It never calls `credits.settle()` or `credits.rollback()`. The reservation increments `question_credits_used` immediately. Every new idempotency key charges again, including a cache hit or a card rebuild after failure. A retry with the same key is worse: the claim stays `reserved`, so `_spend_credit()` raises `GenerationInProgress` forever instead of returning the completed card.
- **Impact:** A “free” reading step drains the same credits that gate question generation, a failed build costs a credit, and a retry cannot recover without a new key (which charges again). The module doc’s “a failure never costs a credit” guarantee does not hold on this route.
- **Fix:** Settle the claim at `actual_n=0` for cached/free cards, roll it back on failure, and commit the claim after a successful build. If concept is intentionally free, do not call `_spend_credit` at all.

### H2. The simplify button is effectively always disabled

- **Where:** `extension/src/ui/cards/concept-card.tsx:42`, `backend/app/schemas/models.py:364`, `backend/app/services/concept_service.py:97-126`.
- **What:** `atMax = simplifiedLevel >= (card.simplified_levels_available ?? 0)`. The backend field defaults to `0`, and `ConceptService._finalise()` never sets it. Unless the model happens to emit `2`, the first render has `simplifiedLevel: 0` and `0 >= 0`, so the button is disabled with “That’s as simple as it gets.”
- **Impact:** “I still don’t get it” is never usable on the normal path. The simplification feature exists in the backend but is hidden by a default value.
- **Fix:** Set `simplified_levels_available = MAX_SIMPLIFICATION_LEVELS` in `_finalise()`, or compare only when the value is non-zero and let the server enforce the cap.

### H3. Hint levels do not advance until an answer is submitted

- **Where:** `backend/app/api/routers/learning.py:336-380`, `backend/app/services/microq_service.py:399-417`, `extension/src/state/learner.ts:390-409`.
- **What:** `request_hint()` returns `next_hint(detail, hints_used=...)`, but it does not persist that a hint was consumed. `_hints_used()` sums `hints_used` from **attempt** rows, which are only written when an answer is submitted. The extension updates `question.hints_used` locally but sends no hint state with the hint request.
- **Impact:** Clicking “Need a hint” twice before answering returns level 1 twice. A reload loses hint progress. The UI label can say “Hint 1 of 3” after the learner has already used one.
- **Fix:** Persist hint consumption server-side (per session/question), or include `hints_used` in the hint request and make the server trust it only after validating the current level. Return the same state from `GET /micro-questions/current`.

### H4. “Show me this step” is a hidden extra attempt, not a reveal

- **Where:** `extension/src/state/learner.ts:412-447`, `extension/src/ui/cards/micro-question-card.tsx:204-209`, `backend/app/api/routers/learning.py:383-427`, `backend/app/services/answer_service.py:110-152`.
- **What:** The UI shows the reveal button once `question.attempts >= 3`. `revealStep()` calls the normal answer endpoint with `hints_used: 3` and the current draft. The backend judges it as a normal answer and increments `attempt_no`. Only when `attempt_no > attempt_cap` (default 8) and `next_question is None` does it append `detail.step_explanation` to `response.feedback`. `next_question` is normally `null` on a wrong answer, so `revealStep()` stores the feedback but keeps `step_explanation` null; the dedicated “This step, in words” panel never appears.
- **Impact:** Between attempts 3 and 8, clicking “Show me this step” consumes an attempt, returns a normal wrong/partial judgment, and shows no explanation. The learner must burn attempts through the server’s cap of 9 before the explanation is appended to feedback, not to the step panel the UI is waiting for. The affordance is actively harmful.
- **Fix:** Add a dedicated reveal endpoint or an explicit `reveal: true` submission that returns `step_explanation` immediately at the UI threshold. Align `attempts`/`attempt_cap` thresholds instead of showing the button at 3 while the server waits for 9.

### H5. Auth state permanently reports “no email / unverified”

- **Where:** `extension/src/api/login.ts:128-132`, `extension/entrypoints/popup/Popup.tsx:95-115`, `extension/entrypoints/popup/Popup.tsx:181-195`.
- **What:** `authState()` returns `{ signedIn: Boolean(accessToken), email: null, emailVerified: false }` unconditionally. The popup calls `api("me")` in the same `load()` but never uses `me.data.email` or `me.data.email_verified`. The successful `auth.login` result is also discarded and replaced by a fresh `auth.state()` call.
- **Impact:** Every signed-in user sees “Email not verified — AI features stay read-only” and no email address, regardless of their real account state. This is a trust-destroying UI bug.
- **Fix:** Derive `AuthState` from `/me` (or return email/verification from login and persist it). Keep the local token-only state only for the pre-network popup paint.

### H6. Logout does not revoke the refresh token

- **Where:** `extension/src/api/login.ts:123-126`, `backend/app/api/routers/auth.py:273-280`.
- **What:** The extension clears local tokens and local cache. `POST /v1/auth/logout` exists and accepts a refresh token, but the route table does not expose it and `logout()` never calls it.
- **Impact:** A copied refresh token remains valid after “Sign out.” This is a security gap, not just a UX gap.
- **Fix:** Add the logout route to the client table and call it with the refresh token before clearing local state. Treat revocation failure as a warning, but attempt it.

### H7. Retries duplicate non-idempotent writes

- **Where:** `extension/src/api/client.ts:282-305`, `extension/src/api/routes.ts:123-129`, `backend/app/services/answer_service.py:110-152`, `backend/app/services/answer_service.py:273-360`.
- **What:** `call()` retries on `network_error` and `timeout`. Only routes marked `idempotent` send `Idempotency-Key`. `microQuestionAnswer` is not marked idempotent and has no key. A timeout after the server processed the answer can therefore submit a second answer and increment `attempt_no` again.
- **Impact:** Duplicate attempts, duplicate XP/mistake projections, and a learner penalized twice for one click. `sessionsCreate` is partly protected by the unique index, but answer submission is not.
- **Fix:** Make answer submission idempotency-keyed and dedupe server-side by `(session, question, key)`, or do not automatically retry writes that mutate attempt state.

### H8. The local cache and response metadata are dead on arrival

- **Where:** `extension/src/api/client.ts:285-291`, `extension/src/api/cache.ts:58-67`, `backend/app/main.py` / all routers (no `{data, meta}` envelope).
- **What:** The client only writes a cache entry when `result.meta.cache_key` exists. The backend returns raw `response_model` payloads and never emits `cache_key`, `content_version`, `credits_remaining`, or `prefs_version` in a `meta` object. `sendOnce()` synthesizes `meta` as empty.
- **Impact:** No cacheable route ever populates the local cache. `fromLocalCache` is always false. Credit changes after concept/generation/answer are not reflected until a separate `/usage` call, and `applyUsageMeta()` is a no-op. The architecture doc’s “revisit costs zero requests” behavior does not exist.
- **Fix:** Either add a consistent response envelope on the backend (or middleware) with cache/credit metadata, or remove the client cache path and always refresh `/usage` after credit-bearing actions. Do not leave both sides claiming a contract neither implements.

### H9. Checklist open state is global, not per problem

- **Where:** `extension/src/state/prefs.ts:30-39`, `extension/src/ui/cards/checklist-card.tsx:47-54`.
- **What:** `checklistRevealed` is a single boolean in `local:ui`. `lastSlug` exists but is never used to scope it. Opening the checklist on one problem leaves the next problem’s checklist already expanded.
- **Impact:** The “earned” checklist can appear pre-revealed on a different problem. This directly undercuts the reveal boundary UX.
- **Fix:** Store the flag per slug (or reset it when the problem slug changes) and use `lastSlug` as part of the key.

### H10. Sign-in fails for unpacked/dev builds unless the origin is configured

- **Where:** `backend/app/core/config.py:290`, `backend/app/core/config.py:325-327`, `extension/src/api/login.ts:67-68`, `backend/app/api/routers/auth.py:87-108`.
- **What:** The default allowlist contains the shipped extension ID `chrome-extension://pmkgnbafanjpmmhphckgglhnpajpepal`. A dev build gets a different runtime ID from `chrome.runtime.getURL("")`. `_safe_return_to()` compares exact origins, so the hosted login page rejects the dev extension’s `return_to`.
- **Impact:** Local development cannot complete the hosted sign-in flow unless `EXTENSION_RETURN_ORIGINS` is explicitly set to the dev ID. The failure appears as “That sign-in link is not valid” on the login page.
- **Fix:** Document the dev-ID override, or support a configurable dev origin in the extension build and default it for non-production.

### H11. This checkout has no environment files, so the extension points at a placeholder

- **Where:** `extension/wxt.config.ts:29-33`, `extension/src/config.ts:14-20`, `extension/.env.example`, `backend/app/core/config.py:21-46`, `backend/app/main.py:43-48`.
- **What:** There is no `extension/.env` and no `backend/.env` in this checkout. The extension falls back to `https://api.codementor.example` for both `VITE_API_BASE_URL` and `host_permissions`. The backend refuses to start without `PYRONITES_URL` and `PYRONITES_KEY`.
- **Impact:** A fresh build cannot call any real backend, and a fresh backend cannot boot. This is an environment blocker rather than a code defect, but it is the most immediate “nothing works” cause in this working copy.
- **Fix:** Create the two `.env` files from the examples as part of setup, and make the extension build fail loudly when the API origin is still the placeholder in a non-production build.

## Medium

- **M1. In-flight dedupe can collapse distinct actions.** `client.ts:269-272` builds the in-flight key from route/params/body but not `idempotencyKey`. Two different user actions with identical route and body can share one promise; the second result is silently lost. Include the idempotency key in the key.
- **M2. Expired-token refresh failure returns a known-expired token.** `client.ts:122-124` returns `current` on a network failure from refresh; `unauthorized` is not retryable (`errors.ts:122-129`). A token that expires mid-flight can fail until the next user action or reload. Return `null` and surface a re-auth state.
- **M3. Hard-coded plan cost ignores the server value.** `overlay.tsx:44` and several `MIN_PLAN_CREDITS` uses override `usage.min_plan_credits`; `/me` does not even include the field in the local Zod schema (`schemas/session.ts:107-113`). If configuration changes, the UI’s “can afford” test is wrong.
- **M4. Time-on-question is always near zero.** `learner.ts:352-361` sets `startedAt` immediately before the answer request. `time_taken_seconds` measures network latency, not learner time. Start the timer when the question is projected.
- **M5. `hint_used` telemetry is mislabeled.** `learner.ts:380-382` fires a `hint_used` event whenever a verdict is not `correct`, even if the learner never requested a hint. This corrupts the funnel metric.
- **M6. Popup renders all-or-nothing.** `Popup.tsx:102-114` uses `Promise.all` for `/usage`, `/progress`, and `/me`; one failure discards the other successful panels. Use `Promise.allSettled` or independent loads.
- **M7. `prefs.set` is a dead, inconsistent path.** `background.ts:84-86` calls the backend but discards the returned `Preferences` (including the new `prefs_version`) and does not persist locally. The popup bypasses it with a direct `api("preferences")`. Remove one path or make the background message authoritative.
- **M8. `conceptSimplify` has no idempotency or credit accounting.** `learning.py:200-245` performs an AI generation on every call, has no `_spend_credit`, and does not stop at the max level on the server. The UI currently hides it (H2), but the endpoint is an unbounded cost leak once the UI is fixed.
- **M9. The concept route has no `response_model`.** `learning.py:172-197` hand-builds the response. The rest of the API is model-driven; this route can drift without OpenAPI validation and is excluded from the contract checks.
- **M10. Contract tests do not assert the client/server header contract.** `backend/tests/test_contract_parity.py` checks paths and methods only. Nothing asserts that every route the server marks idempotent is marked idempotent in `routes.ts`, or that a required header is actually sent. That is why C1 ships green.
- **M11. `X-Client-Version` is sent but not in CORS allow-headers.** `client.ts:197-200` sends it; `main.py:100-107` lists only `Authorization`, `Content-Type`, and `Idempotency-Key`. Extension host permissions usually bypass CORS, so this may not fire in Chrome; verify before treating it as a confirmed break.

## Not the problem (what is actually fine)

- Token storage and `Authorization` attachment live only in the service worker; the content script uses typed messages and never sees a token.
- The Monaco bridge is read-only by construction; there is no `setValue`/`applyEdits` path.
- The backend has a real reveal boundary, per-route identity checks, ownership checks on sessions, and an idempotency design that is sound in principle.
- `open_session()` does reuse an existing active session for `(user, slug)` and the partial unique index protects races. The client failure is not duplicate session creation; it is that the client never asks for the existing state and the limit check happens before reuse.
- The extraction ladder, Zod response validation, and the typed route table are good foundations. The failures are in the wiring between those pieces, not in the overall shape.

## Verification notes

The following were not counted as confirmed defects:

- Whether `chrome.tabs.onUpdated` exposes `info.url` for the login tab with only host permission (rather than the `tabs` permission).
- Whether the hosted login’s 120-second `sendResponse` channel reliably survives MV3 service-worker suspension.
- Whether Chrome enforces CORS preflight for the `X-Client-Version` header in an extension service worker.
- Whether every AI model actually omits `simplified_levels_available`; the server default makes the failure likely, not guaranteed.

## Recommended order

1. Fix C1 and add a contract test that fails when a server-required header is not sent by the client.
2. Fix C5, C6, and C2 so failures and reloads have a recovery path.
3. Fix C3 and C4: existing sessions must be resumable, and approach switching must reset the plan.
4. Fix H3/H4: hints and reveals need explicit server state, not side effects of answer submission.
5. Fix H5/H6/H8: make auth, logout, and response metadata match the contract.
6. Add tests for these flows. The existing suite will not catch a single one of the critical failures above.
