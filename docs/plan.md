# PLAN.md — CodeMentor Extension

## Project Name

**CodeMentor**  
_Working name — change later if needed._

> A browser extension that helps true beginners solve LeetCode-style problems by teaching the required concept first, breaking the problem into sequential micro-questions, and guiding them to write the full solution themselves.

**Positioning:**  
Not another AI answer tool. A step-by-step thinking coach that helps users build the solution themselves.

**Revision:** v2 — rewritten after an architecture gap review. Every rule below that changed carries a `**[v2]**` tag; the change log is in [§16](#16-change-log-v2).

---

## 1. Core Problem

Beginners often open a LeetCode problem and immediately feel stuck.

Common outcomes:

- They copy a solution from YouTube, ChatGPT, or discussion sections.
- They understand the answer partially but cannot reproduce it.
- They feel guilty after using AI.
- They do not learn how to identify the correct DSA approach.
- They repeat the same mistakes because nothing tracks their weak areas.

CodeMentor solves this by making AI act as a **guided tutor**, not an answer generator.

---

## 2. Product Philosophy

1. **Concept before coding.**  
   The user learns the required technique before writing any code.

2. **No direct full solutions — with an explicit reveal boundary. [v2]**  
   Before the user has attempted the problem, nothing in the product contains code or a complete algorithm. After the user has passed **every** micro-question for the chosen approach, the full-solution checklist is released, because at that point the algorithm is earned, not given. See [§3.1](#31-the-reveal-boundary-v2) for the exact artifact-by-artifact rule.

3. **Sequential micro-learning.**  
   A problem is broken into 3–5 small questions that combine into the full solution.

4. **Card-based, not chat-based.**  
   The interface is structured, calm, and sequential. No free-form chatting.

5. **Brute Force first.**  
   Every problem shows Brute Force as the baseline approach before optimized approaches.

6. **Problem-specific explanations.**  
   No generic AI text. Every concept and micro-question must relate directly to the current problem.

7. **Beginner-friendly languages, shipped one at a time. [v2]**  
   Simple English, Hindi, and Odia explanations with light humour and simple diagrams. **A language only becomes selectable once its leak-detector test corpus exists** — the safety validator is language-scoped, and a validator you have not tested in a language is not a validator. English ships in v1; Hindi and Odia follow once their corpora are built and reviewed. See [§14](#14-first-development-milestones).

8. **The product must be able to pay for itself. [v2]**  
   Every AI call is attributed to a user, a task, and a prompt version, so cost-per-learner is a number we can read rather than a number we guess at. See [§12](#12-success-metrics).

---

## 3. Core User Flow

### Step 1: Problem Detection

When a user opens a supported LeetCode problem page, the extension detects:

- Problem title
- Problem statement
- Constraints
- Examples
- Input/output format
- Current code, if available (read only, and only when the user opens Solution Analysis)
- Problem tags, if visible

### Step 2: Approach Discovery

The extension shows possible ways to solve the problem.

Every problem always includes:

1. **Brute Force** — baseline approach

Then it shows only relevant optimized approaches, such as:

- Hash Map
- Two Pointers
- Sliding Window
- Binary Search
- Prefix Sum
- Stack
- Heap
- DFS / BFS
- Backtracking
- Dynamic Programming
- Greedy

The user selects one approach.

### Step 3: Concept Card

After selection, the extension shows a focused concept card:

- Simple explanation
- Why this approach fits this problem
- Small visual/diagram
- Common beginner mistake
- Light humour
- “I still don’t get it” button for an even simpler explanation

No code is shown at this stage.

### Step 4: Micro-Questions

The chosen approach is broken into 3–5 micro-questions.

Example for **Longest Substring Without Repeating Characters** using Sliding Window:

1. What should the window represent in this problem?
2. When should the right side of the window move?
3. When should the left side move?
4. How do we know a character is repeated inside the current window?
5. What value should we track while moving the window?

Micro-questions unlock strictly one at a time.

### Step 5: Full Solution Mode

After **all** micro-questions are completed, the user sees the checklist:

- What data structure will you use?
- What are your variables?
- What is the main loop?
- What is the stopping/updating condition?
- What should you return?

**The checklist is released here, and only here. [v2]** This is the intended product behaviour, not a loophole: a user who has just answered “what should the window represent / when does left move / how do we detect a repeat / what do we track” has already produced the algorithm as their own answers. Hiding the checklist at this point protects nothing and costs the learner the one artifact that turns their answers into code.

Two guards keep the release honest:

- The checklist is **collapsed by default** with a "Reveal the plan" button. It is never sitting on screen unasked.
- Regenerating micro-questions for a switched approach **resets progress to question 1** and costs credits again, so nobody can farm the checklist for free by re-entering the flow. See [§3.2](#32-approach-switching-v2).

The user then writes the complete solution in the real LeetCode editor.

### Step 6: Solution Analysis

After the user completes the problem, they can open the Solution Analysis window.

It shows:

- Time complexity
- Space complexity
- Visual complexity graph
- Line-by-line explanation of important parts
- Edge cases the solution may miss
- Concrete improvement suggestions
- Related tricks for similar problems
- Optional better approach

---

### 3.1 The reveal boundary [v2]

The old rule (“the extension never gives the complete solution”) was unactionable: it forbade the checklist while the product required showing the checklist. The rule is now an explicit per-artifact contract. The AI **never writes code** in any pre-attempt artifact, in any tier.

| Artifact | Visible when | May contain | Leak-check policy |
|---|---|---|---|
| Approach list | On problem detection | Names, one-line reasons | `STRICT` |
| Concept card | After approach selection | Prose, toy diagram | `STRICT` |
| Simplification level 1–2 | On request | Simpler prose | `STRICT` |
| Micro-question prompt *k* | After *k−1* passed | Question text | `STRICT` |
| Hint level 1–2 | On request | Guiding question / pointer | `STRICT` |
| Judge feedback | On each answer | Socratic nudge | `STRICT` |
| Diagram captions and data labels | With the card/question above | Plain text | `STRICT` |
| **Hint level 3 (near-answer)** | After hints 1–2 used | The idea, in plain words, **no code** | `STEP_SCOPED` |
| **Step explanation** | After 8 failed attempts, or explicit "show me this step" | That single step, in words, **no code** | `STEP_SCOPED` |
| **Full-solution checklist** | After the **last** question is passed | The five bullets, **no code** | `EARNED` |
| Solution Analysis | After Solution Mode | Fragments of the user's own code | `EARNED` |

`STEP_SCOPED` and `EARNED` artifacts are still run through the **code-only** check and the sanitiser. They are exempt from the *algorithm-completeness* check, because at the moment they become visible the algorithm is already known to the user. The distinction is enforced server-side in the policy table, not by prompt wording.

### 3.2 Approach switching [v2]

Switching approach mid-problem is allowed, and is now defined:

- Progress **resets to question 1**. The user does not carry progress from one approach into another.
- A new plan version is created; the old one stays readable for free.
- Generating micro-questions costs credits again.
- **Before the switch commits, the UI must show the exact credit cost and the user's remaining balance**, and the user must confirm. There is no silent switch and no accidental switch.

---

## 4. MVP Scope

### Included in v1

- Chrome extension using Manifest V3
- LeetCode problem detection
- Problem extraction
- Brute Force + relevant approach suggestions
- Concept card generation
- 3–5 sequential micro-questions
- Strict one-at-a-time unlocking
- Full-solution checklist (revealed after completion — [§3.1](#31-the-reveal-boundary-v2))
- Final code analysis
- **Verified email required before any credit-bearing or AI-generating action [v2]**
- **Per-user spend attribution for every AI call [v2]**
- English
- Beginner and Intermediate modes
- Basic progress tracking
- Mistake journal
- Question-credit system
- Simple streak and XP system

### Not included in v1

- Firefox/Safari support
- Mobile app
- Team/classroom features
- Paid plans
- Advanced leaderboard
- Full offline AI generation
- Support for every coding platform
- Video explanations
- Social features
- Hindi and Odia content [v2] — see [§2](#2-product-philosophony) rule 7; these ship once their leak corpora exist

---

## 5. Tech Stack

| Layer | Technology |
|---|---|
| Extension framework | WXT |
| Language | TypeScript |
| Extension UI | React |
| Styling | Tailwind CSS |
| UI components | shadcn/ui |
| State management | Zustand |
| Browser storage | WXT storage / `chrome.storage.local` |
| AI backend | Python FastAPI |
| Database, auth, storage | Pyronites |
| Python backend client | `pyronites` |
| AI provider | OpenAI / Gemini / Claude |
| Deployment | Render or Fly.io for backend, Vercel for dashboard if needed |

### Why This Stack

- **WXT** simplifies Manifest V3 extension development, content scripts, service workers, and builds.
- **React + Tailwind** is ideal for the card-based sequential UI.
- **FastAPI** keeps AI keys secure and handles structured AI responses.
- **Pyronites** provides self-hosted auth, SQLite database, REST API, storage, dashboard, and API keys.
- **Zustand** is lightweight enough for extension state without Redux complexity.

---

## 6. System Architecture

```txt
LeetCode Page
      ↓
WXT Content Script
      ↓
Extracts problem data
      ↓
Extension UI
      ↓
FastAPI backend
      ↓
AI provider + Pyronites
      ↓
Structured learning plan
      ↓
Extension renders cards and micro-questions
```

### Important Rules

1. The browser extension must never contain or expose the AI provider API key. All AI calls happen through FastAPI.
2. **The client may display unlock and credit state but never decide it. [v2]**
3. **Connectivity is required from the “Start micro-questions” click onward. [v2]** Detection, extraction, the approach list, and reading any already-saved concept card work offline. Everything after that point needs the server, because answer checking, hint levels, and the unlock cursor are server state. This is stated plainly in the Chrome Web Store listing rather than implied by an offline mode that does not exist.

---

## 7. AI Flow

### Approach Detection

The extension sends the extracted problem data to FastAPI.

FastAPI asks the AI to classify the problem into the 2–4 most relevant approaches.

The response must always include:

- Brute Force
- Relevant optimized approaches
- Confidence score
- Beginner-friendly reason
- When-to-use explanation
- Recommended first approach

### Structured Output

The AI must return strict JSON using a predefined schema.

```json
{
  "problem_type": "string",
  "approaches": [
    {
      "id": "brute_force",
      "name": "Brute Force",
      "confidence": 0.65,
      "simple_reason": "Check every possible substring and keep the longest valid one.",
      "when_to_use": "Use this to understand the problem before optimizing.",
      "difficulty_for_beginner": "easy"
    },
    {
      "id": "sliding_window",
      "name": "Sliding Window",
      "confidence": 0.94,
      "simple_reason": "Move a window across the string and shrink it when a repeat appears.",
      "when_to_use": "Use this when the answer depends on a continuous part of an array or string.",
      "difficulty_for_beginner": "medium"
    }
  ],
  "recommended_first": "sliding_window"
}
```

### Micro-Question Generation [v2]

Generation is **two-stage**, not one big call.

**Stage 1 — the plan shape** (blocking, ~20 s):
- 3–5 micro-questions, each with its prompt, learning goal, answer type, and answer choices
- The full-solution checklist

**Stage 2 — the detail for question *k*** (non-blocking, generated lazily, fast model):
- Rubric and common-wrong-answer patterns for question *k*
- Three hint levels for question *k*
- The step explanation for question *k*
- Optional mini-diagram for question *k*

Stage 2 is produced only when question *k* is actually reached, because most of what it generates is not needed until then. It is cached across users, so for popular problems it is almost always free and instant. **If Stage 2 fails, the question is still delivered** — checking falls back to the learning goal, hints are hidden, and the step explanation falls back to the curated technique notes. Detail failure is never shown to the user as an error.

This split exists because the old single call had to fit five questions plus five rubrics plus fifteen hints plus five step explanations into one response budget. It could not, so five-question plans truncated and then burned the entire retry budget on a failure that retrying cannot fix.

The AI must not reveal the final solution, per [§3.1](#31-the-reveal-boundary-v2).

---

## 8. Database Design

Pyronites tables. **[v2]** tables beyond the original eight are marked.

### users

Stores basic user account data. Includes **`email_verified_at`**, which gates every credit-bearing and AI-generating action.

### user_preferences

```json
{
  "user_id": "user_123",
  "language": "en",
  "difficulty_mode": "beginner",
  "theme": "light",
  "timezone": "Asia/Kolkata",
  "prefs_version": 7
}
```

`timezone` is required for correct streak counting. `prefs_version` lets the extension know its cached copy is stale.

### problem_sessions

```json
{
  "user_id": "user_123",
  "problem_url": "https://leetcode.com/problems/longest-substring-without-repeating-characters/",
  "title": "Longest Substring Without Repeating Characters",
  "selected_approach": "sliding_window",
  "mode": "beginner",
  "language": "en",
  "status": "in_progress",
  "unlocked_index": 2,
  "content_version": 1
}
```

### micro_question_attempts

Append-only. This table is the **single source of truth** for every derived statistic about the learner.

```json
{
  "session_id": "session_456",
  "question_index": 2,
  "user_answer": "Move left until duplicate is removed",
  "was_correct": true,
  "verdict": "correct",
  "attempt_no": 1,
  "hints_used": 0,
  "time_taken_seconds": 42,
  "mistake_type": null,
  "created_at": "2026-10-11T11:54:12Z"
}
```

### mistakes

```json
{
  "user_id": "user_123",
  "concept": "sliding_window",
  "mistake_type": "off_by_one",
  "short_explanation": "User moved left pointer after adding a duplicate instead of before.",
  "problem_url": "..."
}
```

### concept_progress

Denormalised **read model** only. Nothing writes to it during a request; it is projected from `micro_question_attempts` (see ARCHITECTURE §18). Concurrent answers cannot lose an increment because there is no increment to lose.

### review_queue

```json
{
  "user_id": "user_123",
  "concept": "sliding_window",
  "review_due_at": "2026-10-14T11:54:00Z",
  "priority": "high"
}
```

### usage_limits

```json
{
  "user_id": "user_123",
  "window_start": "2026-10-11T11:54:00Z",
  "window_end": "2026-10-11T16:54:00Z",
  "question_credits_used": 3,
  "question_credits_limit": 12,
  "active_sessions": 2
}
```

At most one row per user may have `window_end > now`. This is enforced by a database constraint, not by application logic.

### credit_claims [v2]

The authoritative record of an in-flight or completed credit spend. One row per idempotency key; this is what makes a retried request safe.

```json
{
  "idempotency_key": "uuid",
  "user_id": "user_123",
  "state": "committed",
  "reserved_n": 5,
  "actual_n": 4,
  "session_id": "session_456",
  "created_at": "...",
  "updated_at": "..."
}
```

### credit_ledger [v2]

Append-only audit of every reserve, settle, and rollback. Never consulted to decide whether to charge — it exists so you can answer “what happened to this user's credits” after the fact. Rows carry `(idempotency_key, operation)` and the pair is unique.

### ai_spend [v2]

Every AI call, hit or miss, success or failure, attributed.

```json
{
  "request_id": "req_...",
  "user_id": "user_123",
  "task_id": "microq_shape.v1",
  "prompt_version": "microq_shape.v2",
  "provider": "openai",
  "model": "...",
  "tokens_in": 2100,
  "tokens_out": 880,
  "cached": false,
  "cost_usd": 0.0131,
  "outcome": "ok",
  "created_at": "..."
}
```

### content_cache [v2]

Cross-user generated content, keyed by a server-computed hash. Holds no user text.

### user_stats_events [v2]

Append-only XP and streak source. `user_stats` is a projection of it, so replaying an event cannot double-count.

### events [v2]

Funnel events for [§12](#12-success-metrics). Every write is idempotency-keyed.

---

## 9. Usage Limit System

The extension uses a **question-based credit system**, not an action-based billing system.

### Free Tier Limit

```txt
12 micro-question credits per 5-hour window
Maximum 3 active problem sessions at a time
```

### Credit Rules

| Action | Credit Cost |
|---|---|
| Detect problem | 0 |
| Show approaches | 0 |
| Read concept card | 0 |
| Simplify concept | 0 |
| Answer micro-question | 0 |
| Retry micro-question | 0 |
| View mistake journal | 0 |
| View saved concept cards | 0 |
| Generate a new micro-question | 1 |
| Final code analysis | 0 for MVP |

### Example

If a problem generates 4 micro-questions:

```txt
1 problem = 4 question credits
3 problems = 12 question credits
```

So the user can deeply learn around 3 problems per 5-hour window.

### Cost guardrails that are not credits [v2]

Credits meter **learning depth**. They do not meter **our AI bill**, and a zero-credit action still costs tokens. Four guardrails cover that gap, and all four are invisible to an honest user:

1. **Verified email.** Every AI-generating action requires a verified email address. Unverified accounts can browse, read saved content, and get the approach list, but cannot spend credits or trigger uncached generation.
2. **New-account ramp.** For the first 24 hours after signup, uncached AI generation is charged at 2× against the per-user token budget and capped lower. Bulk accounts get expensive fast.
3. **Per-IP AI budget.** A global budget applies per source IP regardless of account count or authentication. This is the only control that survives “just make five accounts.”
4. **Analysis caps.** Solution Analysis stays free but is capped: a small number of uncached analyses per session per window, plus a distinct-problem cap. Re-running analysis on edited code counts against the cap; a cache hit does not, and a cache hit grants no rewards.

### UX Message

```txt
Question credits: 9 / 12
Resets at 4:54 PM
```

If the user reaches the limit:

```txt
You’ve used all 12 question credits for this 5-hour window.

Your saved concepts, mistake journal, and previous sessions are still available.
Come back at 4:54 PM for more question credits.
```

### On spending [v2]

The credit balance is read from and written by the server under a database constraint. The client never computes it. Before an action that will spend credits — including switching approach — the UI shows the exact cost and the remaining balance, and requires an explicit confirmation.

---

## 10. Feature Roadmap

### Phase 1 — Core MVP

**Goal:** Prove the main learning loop, with the safety and cost machinery already in place.

- WXT extension setup
- LeetCode page detection
- Problem extraction
- FastAPI backend
- AI approach classification
- Brute Force always included
- Concept card generation
- 3–5 micro-questions (two-stage generation)
- Sequential unlocking
- Full-solution checklist behind the reveal boundary
- Basic code analysis
- **Leak detector and its test corpus [v2]**
- **Golden problem set and quality gate [v2]**
- Verified email and the four cost guardrails
- Per-call spend attribution
- English support

**Success criteria:**  
A beginner can go from “I don’t know how to start” to writing their own working solution — and we can read what that learner cost us.

### Phase 2 — Personalization

**Goal:** Make the product feel adaptive.

- **Hindi and Odia support, gated on leak-detector corpus coverage [v2]**
- Beginner / Intermediate modes
- Language preference memory
- Mistake journal
- Concept-wise progress
- Weakness detection
- “I still don’t get it” simplified explanation
- Saved concept cards

**Success criteria:**  
The extension can identify at least one repeated weakness pattern per user, and the leak detector has a passing corpus in every shipped language.

### Phase 3 — Motivation and Retention

**Goal:** Make users return daily.

- Streak system
- XP system
- Visual progress path
- Spaced repetition reminders
- Review queue
- Difficulty scaling
- Better approach suggestions
- Related problem tricks

**Success criteria:**  
Users return within 3 days to review weak concepts.

### Phase 4 — Polish and Expansion

**Goal:** Improve quality and reach.

- Better diagrams
- Code analysis improvements
- More coding platforms
- Firefox support
- Performance optimization
- User feedback system
- Public Chrome Web Store launch

---

## 11. UI Structure

### Main Overlay

```txt
[CodeMentor]

Problem detected: Longest Substring Without Repeating Characters

Possible ways to think:

1. Brute Force
   Try every substring and keep the longest valid one.

2. Sliding Window ★ Recommended
   Move a window across the string and shrink it on repeats.

3. Hash Map
   Remember the last position of every character.

Choose how you want to learn this problem.
```

If the user has already started this problem with a different approach, each option shows a switch tag and the confirmation copy from [§3.2](#32-approach-switching-v2).

### Concept Card

```txt
Sliding Window

Imagine a movable window over the string.

Grow the window from the right.
If a repeat appears, shrink it from the left.

Goal: Keep the window valid and track its maximum size.

[I still don’t get it]
[Start micro-questions]   →  “uses 4 of your 9 question credits”
```

### Micro-Question Card

```txt
Micro-question 1 / 4

What should the window represent?

[Your answer]

[Check understanding]
[Need a hint]           →  1 of 3
```

### Full Solution Mode

```txt
You’ve completed all micro-questions.

Now write the full solution in the LeetCode editor.

▸ Checklist  (collapsed — tap to reveal)
   - Use a set or map to track characters
   - Move right pointer forward
   - Move left pointer when a repeat appears
   - Track the maximum window size

[Open Solution Analysis]
```

### Offline banner [v2]

If the backend is unreachable after micro-questions have started, the overlay says so directly:

```txt
CodeMentor needs a connection to check your answers.
Your place in this problem is saved — nothing you have done is lost.
```

and does not pretend that saved cards are an equivalent experience.

---

## 12. Success Metrics

Track:

- Percentage of users who complete all micro-questions
- Percentage of users who write a full solution afterward
- Average micro-questions completed per session
- Most common mistake types
- Most struggled concepts
- Return rate after 3 days
- Credit usage per user
- Drop-off point: approach selection, concept card, or micro-questions

**Every metric above must be trustworthy. [v2]** Funnel events are idempotency-keyed, so a retried request cannot double-count a learner.

**Cost metrics [v2]** — without these, the free tier is a guess:

- Cost per active user, per week
- Cost per completed session
- Cost per credit spent
- Cost by prompt version (so a prompt change has a measurable price)
- Cost by approach id (so we know which techniques are expensive to teach)
- Cache hit rate by task
- Share of AI calls from accounts younger than 24 hours

**Integrity metrics [v2]:**

- Accounts created per IP per day
- Credit claims in `rolled_back` state, as a share of claims
- Cache rows created per slug per hour (an abuse signal)

---

## 13. Risks and Mitigations

| Risk | Mitigation | Owner / date |
|---|---|---|
| LeetCode DOM changes break extraction | Extraction ladder; semantic selectors; weekly live smoke test; manual-paste fallback; extraction-success metric | Eng, Week 1 |
| AI gives generic explanations | Grounding library; problem-specific prompts; **golden-set eval measuring specificity, running in CI from the first prompt** | Eng, Week 2 |
| AI reveals the solution | Explicit reveal boundary ([§3.1](#31-the-reveal-boundary-v2)); leak detector with three policies; **per-language corpus; golden set includes a leak-rate gate that blocks merge** | Eng, Week 2 |
| Leak detector false-positives in Hindi/Odia | Detector is scoped to code *structure*, not individual keywords; **a language does not ship until its corpus passes** | Eng, Phase 2 |
| Users abuse free AI credits | Verified email; new-account ramp; **per-IP AI budget**; analysis caps; cache-fill bucket | Eng, Week 2 |
| Accounts are farmed | Per-IP budget is global, not per-account; integrity metrics on accounts-per-IP | Eng, Week 2 |
| We cannot tell what a learner costs us | Every AI call writes `ai_spend`; cost metrics in [§12](#12-success-metrics) | Eng, Week 2 |
| Unverified answer/checklist reveals the solution | Reveal boundary; code-only checks on earned artifacts; single-word checklist items | Eng, Week 3 |
| **LeetCode's terms prohibit scripted page reading** | **Blocking question for public distribution. Resolve in Week 1, before any store submission.** Extension reads only the open page, no crawling, no bulk extraction, no credentials or cookies | **PM + legal, Week 1** |
| Pyronites cannot do conditional updates | Credit counters move to a local store with a documented fallback ladder (see ARCHITECTURE §15.4) | Eng, Week 1 |
| Chrome Web Store extension updates lag | `/v1` is additive-only; breaking changes require `/v2` and a long overlap window | Eng, continuous |
| Too many features delay launch | Launch with the core learning loop plus the safety and cost machinery; nothing else | PM |
| Pyronites SQLite scaling limits | Repository/service layer; separate cache/limiter interfaces; WAL enabled from day one | Eng, Week 1 |

---

## 14. First Development Milestones

**The order changed. [v2]** The quality gate and the abuse guards used to land in Week 6, after the prompts and after the mechanisms they were supposed to govern. They now land in Week 2, before the first production prompt exists.

### Week 1

- Initialize WXT + React + TypeScript project
- Create basic LeetCode content script
- Detect problem page
- Extract title, statement, constraints, examples
- Render a simple overlay
- **Spike Pyronites: transactions, conditional updates, partial unique indexes. This answer decides the Week 5 design.**
- **Resolve the LeetCode terms question**
- **Editor bridge spike: confirm which Monaco model is the user's buffer**

### Week 2

- Create FastAPI backend
- Verified-email gate on AI routes
- Rate limiting: per-user buckets **+ global per-IP AI budget**
- Per-call spend attribution
- **Leak detector, its policy table, and its corpus**
- **Golden problem set (30 problems) and the quality-gate runner**
- Add AI approach-classification endpoint
- Implement strict JSON schema
- Show Brute Force + relevant approaches in extension

### Week 3

- Generate concept card
- Add “I still don’t get it”
- Generate 3–5 micro-questions, two-stage
- Implement sequential unlocking
- Implement the reveal boundary end to end, including the checklist
- **Language-scoped leak detector tests**

### Week 4

- Add full-solution checklist with reveal affordance
- Add basic code analysis
- Integrate Pyronites auth
- Save problem sessions and micro-question attempts
- Derived-stats projector (mastery, XP, streak)
- Editor bridge

### Week 5

- Credit service with the claim-based idempotency model
- Active-session cap
- Usage UI states and spend confirmations
- Approach-switch cost confirmation
- Language preference
- Mistake journal
- Concept progress

### Week 6

- Polish UI
- Cost dashboard reading `ai_spend`
- Test with real beginners
- Act on quality-gate findings
- Prepare Chrome Web Store submission

### After v1

- Hindi corpus → Hindi launch
- Odia corpus + native review → Odia launch (beta until reviewed)

---

## 15. Final MVP Definition

The MVP is complete when a user can:

1. Open a LeetCode problem.
2. See Brute Force plus relevant approaches.
3. Select one approach, seeing the credit cost before committing.
4. Read a simple, problem-specific concept card with a diagram.
5. Solve 3–5 sequential micro-questions.
6. Reveal the full-solution checklist, having earned it.
7. Write the full solution themselves.
8. Get complexity and code analysis.
9. See their mistakes and concept progress saved.

**And the business can see it. [v2]** Before we call the MVP done:

- The leak-rate gate passes on the golden set in every shipped language, in CI, on every prompt change.
- Cost-per-completed-session is a number we can read, and it is inside the cap we set.
- A second account from the same IP is measurably more expensive than the first.
- Credits reconcile: claims, ledger, and balance agree for every test we can construct, including concurrent and replayed requests.
- Losing the backend mid-question loses nothing and says so honestly.

If this loop works smoothly, and we can afford it, the product has real value.

---

## 16. Change log (v2)

Rewritten after an architecture gap review. Each row names what was wrong and what the product now says instead.

| # | Was | Now |
|---|---|---|
| 1 | “Never give the complete solution” — forbidden the checklist the product required | Explicit reveal boundary per artifact ([§3.1](#31-the-reveal-boundary-v2)) |
| 2 | Checklist generated with questions, checked by a detector that must reject it | Released only after the last question; collapsed by default; exempt from algorithm-completeness, still checked for code |
| 3 | Switch approach had undefined progress and no cost warning | Progress resets, cost shown and confirmed ([§3.2](#32-approach-switching-v2)) |
| 4 | One call generated five questions, five rubrics, fifteen hints, five explanations | Two-stage: shape call plus lazy per-question detail, with graceful fallback |
| 5 | Abuse controls were all per-user | Verified email, new-account ramp, global per-IP budget, analysis caps ([§9](#9-usage-limit-system)) |
| 6 | No cost attribution anywhere | `ai_spend` on every call; cost metrics are success metrics ([§12](#12-success-metrics)) |
| 7 | Quality gate scheduled after the prompts it governs | Corpus and golden set in Week 2, before the first production prompt |
| 8 | Leak detector keyword list would misfire on Hindi/Odia prose | Detector scoped to code structure; language ships only after its corpus passes |
| 9 | Offline fallback implied more than existed | Explicit “online required from micro-questions onward”, stated in the store listing |
| 10 | Metrics computed from replayable events | Events idempotency-keyed; stats projected from append-only facts |
| 11 | LeetCode ToS was an unowned open question | Blocking Week 1 item with an owner |
| 12 | Milestone order ran build-then-guard | Guards land before the thing they guard |