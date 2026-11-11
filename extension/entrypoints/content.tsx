/**
 * Always-on content script (§5.1, §5.2).
 *
 * Owns SPA navigation detection, the extraction ladder, and a lightweight
 * launcher. It never calls the backend directly and never holds a token.
 *
 * The overlay UI lives in a separate unlisted script (`overlay-ui.tsx`),
 * injected by the service worker when the learner opens it. Bundling React and
 * the cards here cost ~207 ms of main-thread evaluation on every problem page,
 * so that payload is only paid for once it is actually used.
 */

import { defineContentScript } from "wxt/utils/define-content-script";

import { extractProblem, slugFromUrl, type Rung } from "../src/extraction/ladder";
import { log } from "../src/state/client";
import { flush, track } from "../src/telemetry";
import type { ProblemBridge } from "../src/ui/overlay-bridge";

const RUNG_LABEL: Record<Rung, string> = {
  embedded: "read from the page's own data",
  dom: "read from the page structure",
  text: "read from the visible text (some detail may be missing)",
  manual: "pasted by hand",
};

const LAUNCHER_ID = "codementor-launcher";

let currentSlug: string | null = null;
let extractToken = 0;
let observer: MutationObserver | null = null;
let launcher: HTMLButtonElement | null = null;

function injectLauncherStyles(): void {
  if (document.getElementById("codementor-launcher-style")) return;
  const style = document.createElement("style");
  style.id = "codementor-launcher-style";
  style.textContent = `
    #${LAUNCHER_ID} {
      all: initial;
      position: fixed;
      right: 20px;
      bottom: 20px;
      z-index: 2147483000;
      display: flex;
      align-items: center;
      gap: 8px;
      height: 40px;
      padding: 0 16px;
      border: 0;
      border-radius: 9999px;
      background: #111827;
      color: #ffffff;
      font: 600 13px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      letter-spacing: -0.01em;
      cursor: pointer;
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.24), 0 1px 2px rgba(0, 0, 0, 0.12);
      transition: transform 150ms ease, box-shadow 150ms ease;
    }
    #${LAUNCHER_ID}:hover {
      transform: translateY(-1px);
      box-shadow: 0 10px 28px rgba(0, 0, 0, 0.28), 0 1px 2px rgba(0, 0, 0, 0.12);
    }
    #${LAUNCHER_ID}:focus-visible {
      outline: 2px solid #6366f1;
      outline-offset: 2px;
    }
    @media (prefers-color-scheme: dark) {
      #${LAUNCHER_ID} { background: #f9fafb; color: #111827; }
    }
  `;
  (document.head ?? document.documentElement).append(style);
}

function showLauncher(): void {
  // Opening the overlay removes the launcher, and an SPA route change on the
  // same problem calls this again; do not resurrect it behind the panel.
  if (window.__codementorUi) return;
  injectLauncherStyles();
  if (!launcher) {
    const button = document.createElement("button");
    button.id = LAUNCHER_ID;
    button.type = "button";
    button.setAttribute("aria-label", "Open CodeMentor");
    button.innerHTML =
      '<span aria-hidden="true" style="width:7px;height:7px;border-radius:50%;background:#22c55e"></span><span>CodeMentor</span>';
    button.addEventListener("click", () => void openUi());
    (document.body ?? document.documentElement).append(button);
    launcher = button;
  }
}

function removeLauncher(): void {
  launcher?.remove();
  launcher = null;
}

async function openUi(): Promise<void> {
  if (window.__codementorUi) {
    window.__codementorUi.focus();
    return;
  }
  try {
    const res = (await chrome.runtime.sendMessage({ t: "ui.open" })) as
      | { ok?: boolean }
      | undefined;
    if (!res?.ok) log("warn", "CodeMentor could not open the overlay.");
  } catch (cause) {
    log("warn", `CodeMentor could not open the overlay: ${String(cause)}`);
  }
}

function teardown(): void {
  currentSlug = null;
  observer?.disconnect();
  observer = null;
  window.__codementorUi?.unmount();
  removeLauncher();
  delete window.__codementorProblem;
}

async function onRouteChange(): Promise<void> {
  const slug = slugFromUrl();

  if (!slug) {
    teardown();
    return;
  }

  if (slug === currentSlug) {
    showLauncher();
    return;
  }

  currentSlug = slug;
  extractToken += 1;
  const token = extractToken;

  const result = await extractProblem({ slug });
  if (token !== extractToken) return;

  const problem = result.problem ?? null;
  const note = result.rung ? RUNG_LABEL[result.rung] : null;
  const bridge: ProblemBridge = { slug, problem, note };
  window.__codementorProblem = bridge;

  if (problem) {
    track("problem_detected", {
      slug,
      rung: result.rung,
      quality: problem.extraction_quality,
    });
  }

  if (window.__codementorUi) window.__codementorUi.setProblem(slug, problem, note);
  showLauncher();
}

/**
 * Re-extract only when the slug changed or the description node was replaced —
 * never on every mutation, which would burn CPU for nothing (§5.2).
 */
function watchDescription(): void {
  observer?.disconnect();
  const target =
    document.querySelector('[data-e2e-locator="question-detail-container"]') ??
    document.querySelector('div[id^="description"]') ??
    document.body;
  if (!target) return;

  let lastLength = target.textContent?.length ?? 0;
  observer = new MutationObserver(() => {
    const length = target.textContent?.length ?? 0;
    if (Math.abs(length - lastLength) < 200) return;
    lastLength = length;
    const slug = currentSlug;
    if (!slug || slugFromUrl() !== slug) return;
    void extractProblem({ slug }).then((result) => {
      // The page can navigate while this extraction is in flight; do not let a
      // stale result overwrite the newer problem's bridge.
      if (currentSlug !== slug || slugFromUrl() !== slug) return;
      const problem = result.problem ?? null;
      const note = result.rung ? RUNG_LABEL[result.rung] : null;
      const bridge: ProblemBridge = { slug, problem, note };
      window.__codementorProblem = bridge;
      if (problem) window.__codementorUi?.setProblem(slug, problem, note);
    });
  });
  observer.observe(target, { childList: true, subtree: true, characterData: true });
}

function installHistoryHook(): void {
  const push = history.pushState.bind(history);
  const replace = history.replaceState.bind(history);
  let scheduled = false;

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    // Debounced: the description DOM lands a beat after the route does.
    setTimeout(() => {
      scheduled = false;
      void onRouteChange().then(watchDescription);
    }, 300);
  };

  history.pushState = (...args) => {
    push(...args);
    schedule();
  };
  history.replaceState = (...args) => {
    replace(...args);
    schedule();
  };
  window.addEventListener("popstate", schedule);
}

export default defineContentScript({
  matches: ["https://leetcode.com/problems/*"],
  runAt: "document_idle",

  main() {
    installHistoryHook();

    window.__codementorRemoveLauncher = removeLauncher;
    window.__codementorShowLauncher = showLauncher;

    // Debug helpers for diagnosing in the browser console on leetcode.com.
    // The overlay script replaces `state` and `prefs` once it is injected.
    window.__codementorDebug = {
      slug: () => slugFromUrl(),
      state: () => undefined,
      prefs: () => undefined,
      mounted: () => Boolean(window.__codementorUi),
      open: () => openUi(),
      close: () => window.__codementorUi?.unmount(),
      extract: () => extractProblem({ slug: slugFromUrl() ?? undefined }),
    };

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") void flush();
    });

    void onRouteChange().then(watchDescription);

    // WXT calls this when the content script is torn down.
    return () => {
      observer?.disconnect();
      observer = null;
      removeLauncher();
      void flush();
    };
  },
});
