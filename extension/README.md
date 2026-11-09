# CodeMentor — Chrome extension

A step-by-step thinking coach for LeetCode. It teaches the concept, asks a few
small questions, and gets out of the way so the learner writes the solution
themselves.

This repository is the **extension only**. The FastAPI backend described in
`ARCHITECTURE.md` §6 is a separate deployable and is not here; the extension is
built against the contract in §20.

---

## Running it

```bash
npm install
cp .env.example .env          # set VITE_API_BASE_URL
npm run dev                   # watch build, loads as an unpacked extension
npm run build                 # -> .output/chrome-mv3/
npm run zip                   # -> .output/*.zip, ready for the Web Store
npm run compile               # tsc --noEmit
npm test                      # vitest
npm run test:e2e              # build for the fake API, then Playwright
npm run check                 # compile + test + build
```

`npm run test:e2e` builds the extension with `VITE_API_BASE_URL=http://127.0.0.1:8787`,
starts a stateful fake backend, loads the unpacked extension in Chromium, and
drives sign-in, extraction, approach switching, resume, hints, reveal,
checklist unlock, and analysis. It does not need Pyronites or AI credentials.

If the pinned Playwright browser is not in the local cache, point the harness at
an installed Chromium:

```powershell
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE="C:\path\to\chrome.exe"
npm run test:e2e
```

Load it via `chrome://extensions` → *Developer mode* → *Load unpacked* →
`.output/chrome-mv3`.

`VITE_API_BASE_URL` is read at build time **and** in `wxt.config.ts` (it appears
in `host_permissions`), so a staged build points at a different backend without a
code change. A production build refuses to start while the value is still the
placeholder; run `npm run dev` if you only need the UI without a backend.

Both halves need their own environment file. This checkout ships the examples,
not filled-in secrets:

```bash
cp extension/.env.example extension/.env   # VITE_API_BASE_URL
cp backend/.env.example backend/.env       # PYRONITES_KEY + one AI provider key
```

### Sign-in from an unpacked build

The backend allowlist compares **exact** extension origins. The build pins a
manifest `key`, so an unpacked build loads with the same ID as the packaged CRX
(`ncbohgigmifjgekpfeebkognlogpflfa`) and that ID is already allowed by default.
If Chrome ever reports a different ID (for example a source build with the key
removed), sign-in fails with "That sign-in link is not valid" until the dev ID
is allowed:

1. Load the unpacked build via `chrome://extensions`.
2. Copy its ID from the extension card.
3. Set `EXTENSION_RETURN_ORIGINS=chrome-extension://<dev-id>` in
   `backend/.env` and restart the backend. Use a comma-separated list to allow
   both the dev and shipped IDs.

---

## What it does

| Stage | Behaviour |
|---|---|
| Detect | SPA navigation is watched; the problem is extracted by a four-rung ladder |
| Approaches | Brute Force first, then up to three relevant ones, with a ★ on the recommendation |
| Concept | One problem-specific card, a diagram, a common beginner mistake, and "I still don't get it" |
| Micro-questions | 3–5 questions, one at a time, six answer types, progressive hints |
| Solution mode | The checklist is **collapsed until asked for**, then Solution Analysis |
| Analysis | Complexity with a growth-rate chart, line-by-line notes, edge cases, improvements |

---

## Structure

```
entrypoints/
  background.ts        service worker: the only code that talks to the backend
  content.tsx          extraction ladder + Shadow-DOM overlay
  bridge.content.ts    MAIN-world script that reads the Monaco buffer (read-only)
  popup/               login, settings, usage, progress graphs

src/
  schemas/             Zod contracts mirroring the backend (§20)
  api/                 route table, HTTP client, auth, local cache
  bridge/              MAIN-world protocol and the content-script side of it
  extraction/          embedded JSON → semantic DOM → text heuristics → manual paste
  diagrams/            scene model, deterministic layouts, ASCII fallback
  charts/              complexity graph + progress graphs (plain SVG, d3 for position only)
  state/               Zustand learner store, preferences, message client
  ui/                  shadcn components, design tokens, cards, overlay shell
  i18n/                UI strings (AI content language comes from the backend)

public/fonts/          vendored Noto Devanagari + Oriya (SIL OFL)
tests/                 constraint parser, HTML conversion, diagram layout, chart verdicts
```

Section references (`§5.4`, `§10.3`, …) point at `ARCHITECTURE.md` at the repo
root.

---

## Decisions worth knowing

**The service worker is the only thing that talks to the backend.** The content
script sends a route id and gets a typed result. It never holds a token, never
sets an `Authorization` header, and never builds a URL.

**The client never computes a cache key.** The server returns `cache_key` and
`content_version`; we store the payload alongside those exact values. The local
index is keyed by a request pointer so a revisit costs zero requests until the
backend's content version moves (§5.6, §15.8).

**The bridge is read-only by construction.** There is no `setValue`, no
`executeEdits`, no `applyEdits` anywhere in `bridge.content.ts`. That property —
not the nonce, not the origin check — is what makes it safe. Origin checks stop
other extensions, not scripts on leetcode.com, which can already read the editor.

**The diagram spec has no `reveals_solution` field.** `LearningDiagramSpec` is
`strict` on every object, so a concept or micro-question diagram *cannot* carry
that capability. Full traces use a separate type that only the analysis route
constructs (§12.5).

**CodeMentor never writes to the LeetCode editor.** Ever.

**The checklist is earned and collapsed.** The server returns `409
checklist_locked` until the last question is passed, and the card renders as a
single collapsed row until tapped.

---

## Assumptions that must be confirmed before launch

These are the items `ARCHITECTURE.md` marks `[Verify]`. Each one is built to
degrade rather than to break.

| # | Assumption | How the code behaves if it is wrong |
|---|---|---|
| 1 | **LeetCode DOM selectors.** The ladder tries embedded page JSON first, then semantic DOM hooks, then text heuristics, then a manual-paste card. | Extraction degrades to `partial`, then to manual paste. The learner never sees a crash — but if rung 1 stops working, rung 2 is the thing to fix, and the week-1 selector verification is what finds that. |
| 2 | **Which Monaco model is the user's buffer.** `getModels()[0]` is often the wrong buffer. | The bridge picks last-focused → single-visible → language-matched, and sets `ambiguous: true` whenever it could not prove the answer. The UI asks instead of guessing, and the buffer falls back to the editor textarea, then to paste. |
| 3 | **Monaco's internal `_codeEditorService`** (used to map a DOM container back to its model). | If absent, model resolution falls through to the visible-model and DOM-scrape paths, which always report `ambiguous: true`. |
| 4 | **GitHub OAuth.** The backend serves the sign-in page, owns the GitHub callback, and returns a one-time code the popup exchanges for tokens. No extension permission is needed. | If GitHub credentials are missing the login page reports sign-in as unavailable; nothing else breaks. Register the backend's `/v1/auth/extension/github/callback` URL on the GitHub OAuth app. |
| 5 | **Backend response shapes.** Every response is re-validated with Zod in the service worker. | A malformed payload becomes a typed `invalid_response` error card, never a crash inside a third-party page. |

---

## Not in v1

Hindi and Odia UI chrome is present but gated: a language ships only once its
leak-detector corpus passes (`§11.4`), so both fall back to English strings until
review is done. No offline mode is claimed — connectivity is required from the
"Start micro-questions" click onward, and the overlay says so plainly.

---

## Fonts

`public/fonts/` holds Noto Sans Devanagari and Noto Sans Oriya (SIL Open Font
License 1.1). They are injected into the shadow root at runtime with absolute
extension URLs, because a relative `url()` inside a shadow root would resolve
against `leetcode.com`.