/**
 * Content script (§5.1, §5.2).
 *
 * Owns SPA navigation detection, the extraction ladder, and the Shadow-DOM
 * overlay. It never calls the backend directly and never holds a token — both
 * belong to the service worker (ADR-2).
 */

import { defineContentScript } from "wxt/utils/define-content-script";
import type { ContentScriptContext } from "wxt/utils/content-script-context";
import { createShadowRootUi, type ShadowRootContentScriptUi } from "wxt/utils/content-script-ui/shadow-root";
import { createRoot, type Root } from "react-dom/client";

import "../src/ui/styles.css";
import { Overlay, refreshUsage, syncMe } from "../src/ui/overlay";
import { injectFonts } from "../src/ui/fonts";
import { extractProblem, slugFromUrl, type Rung } from "../src/extraction/ladder";
import { useLearnerStore } from "../src/state/learner";
import { log } from "../src/state/client";
import { prefsStore } from "../src/state/prefs";
import { flush, track } from "../src/telemetry";
import type { Theme } from "../src/schemas";

const RUNG_LABEL: Record<Rung, string> = {
  embedded: "read from the page's own data",
  dom: "read from the page structure",
  text: "read from the visible text (some detail may be missing)",
  manual: "pasted by hand",
};

let ui: ShadowRootContentScriptUi<Root> | null = null;
let currentSlug: string | null = null;
let extractToken = 0;
let observer: MutationObserver | null = null;

async function mountOverlay(ctx: ContentScriptContext): Promise<ShadowRootContentScriptUi<Root>> {
  if (ui) return ui;
  ui = await createShadowRootUi<Root>(ctx, {
    name: "codementor-overlay",
    position: "overlay",
    alignment: "bottom-right",
    zIndex: 2_147_483_000,
    isolateEvents: true,
    onMount(container: HTMLElement) {
      const root = createRoot(container);
      root.render(<Overlay />);
      void injectFonts(container.getRootNode() as ShadowRoot);
      return root;
    },
    onRemove(root: Root | undefined) {
      root?.unmount();
    },
  });
  ui.mount();
  return ui;
}

function unmountOverlay(): void {
  ui?.remove();
  ui = null;
}

/** Follow LeetCode's light/dark and the user's stored preference (§5.5). */
async function applyTheme(mounted: ShadowRootContentScriptUi<Root>): Promise<void> {
  const prefs = await prefsStore.getValue();
  const mode: Theme = prefs.theme;
  const dark =
    mode === "dark" ||
    (mode === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  mounted.shadowHost.classList.toggle("dark", dark);
}

function watchSystemTheme(): void {
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => {
      if (ui) void applyTheme(ui);
    });
}

async function onRouteChange(ctx: ContentScriptContext): Promise<void> {
  const slug = slugFromUrl();

  if (!slug) {
    currentSlug = null;
    observer?.disconnect();
    observer = null;
    unmountOverlay();
    useLearnerStore.getState().reset();
    return;
  }

  const mounted = await mountOverlay(ctx);
  await applyTheme(mounted);

  if (slug === currentSlug) return;
  currentSlug = slug;
  extractToken += 1;
  const token = extractToken;

  const store = useLearnerStore.getState();
  store.reset();
  store.setPending("extract");

  const result = await extractProblem({ slug });
  if (token !== extractToken) return;

  if (!result.problem) {
    store.setProblem(null, null);
    useLearnerStore.setState({ stage: "manual", pending: "none" });
    return;
  }

  store.setProblem(result.problem, result.rung ? RUNG_LABEL[result.rung] : null);
  track("problem_detected", {
    slug,
    rung: result.rung,
    quality: result.problem.extraction_quality,
  });

  try {
    await refreshUsage();
  } catch {
    // Credits are a convenience here. An expired token or network blip must
    // not strand the extraction spinner or hide the approach list.
  }
  useLearnerStore.setState({ pending: "none" });

  const resumed = await store.resumeSession();
  if (!resumed) await store.loadApproaches();
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
    if (slugFromUrl() !== currentSlug) return;
    useLearnerStore.getState().setPending("extract");
    void extractProblem({ slug: currentSlug ?? undefined }).then((result) => {
      if (result.problem) useLearnerStore.getState().setProblem(result.problem);
      useLearnerStore.setState({ pending: "none" });
    });
  });
  observer.observe(target, { childList: true, subtree: true, characterData: true });
}

function installHistoryHook(ctx: ContentScriptContext): void {
  const push = history.pushState.bind(history);
  const replace = history.replaceState.bind(history);
  let scheduled = false;

  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    // Debounced: the description DOM lands a beat after the route does.
    setTimeout(() => {
      scheduled = false;
      void onRouteChange(ctx).then(watchDescription);
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
  // Styles are scoped to our shadow root, not injected into leetcode.com (§5.1).
  cssInjectionMode: "ui",

  main(ctx) {
    installHistoryHook(ctx);
    watchSystemTheme();

    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") void flush();
    });

    // Keep the credit chip and the language honest without polling: revalidate
    // whenever the tab regains focus, which is also when preferences get
    // re-checked against `prefs_version` (§16.2, §5.6).
    window.addEventListener("focus", () => {
      void syncMe().catch(() => undefined);
    });

    void onRouteChange(ctx).then(watchDescription);

    syncMe().catch((cause) => log("info", `Not signed in yet: ${String(cause)}`));

    // WXT calls this when the content script is torn down.
    return () => {
      observer?.disconnect();
      observer = null;
      unmountOverlay();
      void flush();
    };
  },
});