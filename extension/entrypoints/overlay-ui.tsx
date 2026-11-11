/**
 * On-demand overlay UI.
 *
 * An unlisted script injected by the service worker when the learner opens
 * CodeMentor (see the `ui.open` message in `background.ts`). Keeping React and
 * the cards out of the always-on content script removes ~207 ms of main-thread
 * evaluation from every problem page.
 *
 * It shares the extension's isolated world with `content.tsx`, so the extracted
 * problem is handed over through `window.__codementorProblem`.
 *
 * The React graph is imported inside `mount()`, not at module scope: WXT
 * evaluates entrypoints in Node at build time, and `react-aria` touches
 * `window` on import.
 */

import type { Root } from "react-dom/client";
import { defineUnlistedScript } from "wxt/utils/define-unlisted-script";
import type { ContentScriptContext } from "wxt/utils/content-script-context";
import {
  createShadowRootUi,
  type ShadowRootContentScriptUi,
} from "wxt/utils/content-script-ui/shadow-root";

import { flush } from "../src/telemetry";
import type { OverlayHandle, ProblemBridge } from "../src/ui/overlay-bridge";

export default defineUnlistedScript({
  main() {
    const existing = window.__codementorUi;
    if (existing) {
      existing.focus();
      return;
    }

    // Claim the slot before the first `await`. `mount()` imports the React
    // graph, fetches the stylesheet, and builds the shadow root; a second
    // injection during that window (a double click, or a second `ui.open`
    // message) would otherwise mount a second overlay and leak its listeners.
    let cancelled = false;
    const claim: OverlayHandle = {
      unmount: () => {
        cancelled = true;
      },
      setProblem: () => undefined,
      focus: () => undefined,
    };
    window.__codementorUi = claim;

    void mount(() => cancelled).catch((cause) => {
      if (window.__codementorUi === claim) delete window.__codementorUi;
      window.__codementorShowLauncher?.();
      console.warn("[codementor:ui] could not mount the overlay", cause);
    });
  },
});

async function loadOverlayCss(): Promise<string> {
  try {
    const url = chrome.runtime.getURL("assets/overlay-styles.css");
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // The shadow root needs `:host` because `:root` does not match inside it.
    return (await res.text()).replaceAll(":root", ":host");
  } catch (cause) {
    console.warn("[codementor:ui] could not load the overlay stylesheet", cause);
    return "";
  }
}

async function mount(isCancelled: () => boolean): Promise<void> {
  const [{ Overlay, syncMe }, { useLearnerStore }, { prefsStore, resolveTheme }, { createRoot }, { injectFonts }] =
    await Promise.all([
      import("../src/ui/overlay"),
      import("../src/state/learner"),
      import("../src/state/prefs"),
      import("react-dom/client"),
      import("../src/ui/fonts"),
    ]);

  let ui: ShadowRootContentScriptUi<Root> | null = null;
  let mountedSlug: string | null = null;
  let stopTheme: (() => void) | null = null;

  function applyProblem(bridge: ProblemBridge | null): void {
    const store = useLearnerStore.getState();

    // Same problem: a re-extraction only refreshes the data.
    if (bridge && bridge.slug === mountedSlug) {
      store.setProblem(bridge.problem, bridge.note);
      return;
    }

    mountedSlug = bridge?.slug ?? null;
    store.reset();
    store.setProblem(bridge?.problem ?? null, bridge?.note ?? null);

    if (bridge?.problem) {
      void hydrate();
    } else {
      useLearnerStore.setState({ stage: "manual", pending: "none" });
      void syncMe().catch(() => undefined);
    }
  }

  async function hydrate(): Promise<void> {
    const store = useLearnerStore.getState();
    try {
      await syncMe();
    } catch {
      // The overlay still renders; credits and prefs revalidate on focus.
    }
    try {
      const resumed = await store.resumeSession();
      if (!resumed) await store.loadApproaches();
    } catch {
      // Keep the manual entry path usable if resuming fails.
    }
  }

  async function syncTheme(): Promise<void> {
    if (!ui) return;
    const host = ui.shadowHost;

    const apply = async () => {
      try {
        const prefs = await prefsStore.getValue();
        host.classList.toggle("dark", resolveTheme(prefs.theme));
      } catch {
        // Keep the default theme when prefs are unavailable.
      }
    };

    await apply();

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => void apply();
    media.addEventListener("change", onChange);
    stopTheme = () => media.removeEventListener("change", onChange);
  }

  // One listener per open; without removal they stack across close/reopen and
  // each focus fires one `syncMe`.
  const onFocus = () => {
    void syncMe().catch(() => undefined);
  };

  function unmount(): void {
    window.removeEventListener("focus", onFocus);
    stopTheme?.();
    stopTheme = null;
    ui?.remove();
    ui = null;
    mountedSlug = null;
    delete window.__codementorUi;
    void flush();
    window.__codementorShowLauncher?.();
  }

  // `createShadowRootUi` only needs `onInvalidated` and the CSS mode; there is
  // no ContentScriptContext for an executeScript-injected script.
  const ctx = {
    options: {},
    onInvalidated: () => undefined,
  } as unknown as ContentScriptContext;

  const css = await loadOverlayCss();
  if (isCancelled()) {
    delete window.__codementorUi;
    return;
  }

  ui = await createShadowRootUi<Root>(ctx, {
    name: "codementor-overlay",
    position: "overlay",
    alignment: "bottom-right",
    zIndex: 2_147_483_000,
    isolateEvents: true,
    css,
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

  if (isCancelled()) {
    delete window.__codementorUi;
    return;
  }

  ui.mount();
  window.__codementorRemoveLauncher?.();

  window.__codementorUi = {
    unmount,
    setProblem(slug, problem, note) {
      applyProblem({ slug, problem, note });
    },
    focus() {
      ui?.shadowHost.scrollIntoView({ block: "nearest" });
    },
  };

  window.__codementorDebug = {
    ...(window.__codementorDebug ?? {}),
    state: () => useLearnerStore.getState(),
    prefs: () => prefsStore.getValue(),
    mounted: () => Boolean(ui),
    syncMe: () => syncMe(),
  };

  window.addEventListener("focus", onFocus);
  applyProblem(window.__codementorProblem ?? null);
  void syncTheme();
}
