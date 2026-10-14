/**
 * MAIN-world bridge (§5.4).
 *
 * Monaco virtualizes lines, so scraping the editor DOM returns truncated code.
 * The page owns the `monaco` global, so the only way to read a complete buffer
 * is from the page's own world. This script does exactly that.
 *
 * **It is read-only by construction.** There is no `setValue`, `executeEdits`
 * or `applyEdits` call anywhere in this file � that property is the security
 * story (§18.2). The nonce and origin check are hygiene: they stop other
 * extensions' isolated worlds, not scripts on leetcode.com, which already share
 * the origin and can read the editor themselves.
 */

import { defineContentScript } from "wxt/utils/define-content-script";

import {
  BRIDGE_PING,
  BRIDGE_PONG,
  BRIDGE_REQUEST,
  BRIDGE_RESPONSE,
  BRIDGE_TAG,
  type BridgeResponse,
  type BridgeVia,
} from "../src/bridge/protocol";

type MonacoModel = {
  getValue: () => string;
  getLanguageId: () => string;
  isDisposed?: () => boolean;
};

type MonacoEditorLike = { getModel: () => MonacoModel | null };

type MonacoLike = {
  editor: {
    getModels: () => MonacoModel[];
    /**
     * Monaco's standalone code-editor service is internal but long-stable, and
     * it is the only way to map a DOM container back to its model without
     * guessing. Everything degrades gracefully when it is absent.
     */
    _codeEditorService?: { getCodeEditor: (node: Node) => MonacoEditorLike | null };
  };
};

function monaco(): MonacoLike | undefined {
  return (window as unknown as { monaco?: MonacoLike }).monaco;
}

/** The last `.monaco-editor` container the learner interacted with. */
let lastFocusedContainer: Element | null = null;

function noteInteraction(event: Event): void {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const container = target.closest(".monaco-editor");
  if (container) lastFocusedContainer = container;
}

function editorFor(container: Element): MonacoEditorLike | null {
  const service = monaco()?.editor?._codeEditorService;
  if (!service) return null;
  try {
    return service.getCodeEditor(container) ?? null;
  } catch {
    return null;
  }
}

function liveModels(): MonacoModel[] {
  const editor = monaco()?.editor;
  if (!editor?.getModels) return [];
  try {
    return editor.getModels().filter((model) => !model.isDisposed?.());
  } catch {
    return [];
  }
}

function visibleContainers(): Element[] {
  return Array.from(document.querySelectorAll(".monaco-editor")).filter((el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  });
}

function isVisible(model: MonacoModel): boolean {
  return visibleContainers().some((container) => editorFor(container)?.getModel() === model);
}

function activeLanguageHint(): string {
  const tab = document.querySelector<HTMLElement>('button[aria-label*="language" i]');
  return (tab?.textContent ?? "").trim().toLowerCase();
}

/**
 * Last resort: read the rendered lines of one container. Lossy by construction �
 * Monaco only mounts visible lines � so this path always reports
 * `ambiguous: true` and the UI asks before analysing anything.
 */
function scrape(container: Element): string {
  const lines = Array.from(container.querySelectorAll(".view-line"));
  return lines.map((line) => (line.textContent ?? "").replace(/ /g, " ")).join("\n");
}

type Pick = { model: MonacoModel; via: BridgeVia; ambiguous: boolean };

function pickModel(): Pick | null {
  const all = liveModels();

  // 1. The container the learner last interacted with.
  if (lastFocusedContainer?.isConnected) {
    const model = editorFor(lastFocusedContainer)?.getModel();
    if (model) return { model, via: "focused_editor", ambiguous: false };
  }
  if (all.length === 0) return null;

  const visible = all.filter(isVisible);

  // 2. Unambiguous: one buffer total, and it is on screen.
  if (visible.length === 1 && all.length === 1) {
    return { model: visible[0]!, via: "visible_editor", ambiguous: false };
  }

  // 3. Several buffers on screen. Prefer the one matching the language tab,
  //    and admit we guessed when more than one remains.
  if (visible.length > 0) {
    const hint = activeLanguageHint();
    if (hint) {
      const match = visible.find((model) =>
        model.getLanguageId().toLowerCase().includes(hint) ||
        hint.includes(model.getLanguageId().toLowerCase()),
      );
      if (match) return { model: match, via: "uri_match", ambiguous: visible.length > 1 };
    }
    return { model: visible[0]!, via: "visible_editor", ambiguous: true };
  }

  // 4. Nothing on screen; exactly one buffer exists, so it is the only one.
  if (all.length === 1) return { model: all[0]!, via: "uri_match", ambiguous: false };

  return null;
}

function answer(nonce: string): BridgeResponse {
  const picked = pickModel();
  if (picked) {
    try {
      return {
        tag: BRIDGE_TAG,
        type: BRIDGE_RESPONSE,
        nonce,
        code: picked.model.getValue(),
        languageId: picked.model.getLanguageId(),
        ambiguous: picked.ambiguous,
        via: picked.via,
      };
    } catch {
      // The model was disposed between selection and read; fall through.
    }
  }

  const container =
    lastFocusedContainer?.isConnected ? lastFocusedContainer : (visibleContainers()[0] ?? null);
  if (container) {
    const code = scrape(container);
    if (code.trim()) {
      return {
        tag: BRIDGE_TAG,
        type: BRIDGE_RESPONSE,
        nonce,
        code,
        languageId: "",
        ambiguous: true,
        via: "dom_scrape",
      };
    }
  }

  return {
    tag: BRIDGE_TAG,
    type: BRIDGE_RESPONSE,
    nonce,
    code: "",
    languageId: "",
    ambiguous: true,
    via: "none",
  };
}

export default defineContentScript({
  matches: ["https://leetcode.com/problems/*"],
  world: "MAIN",
  runAt: "document_idle",
  main() {
    document.addEventListener("focusin", noteInteraction, true);
    document.addEventListener("pointerdown", noteInteraction, true);

    window.addEventListener("message", (event: MessageEvent) => {
      if (event.source !== window) return;
      const data = event.data as { tag?: string; type?: string; nonce?: string } | null;
      if (data?.tag !== BRIDGE_TAG || typeof data.nonce !== "string") return;

      if (data.type === BRIDGE_PING) {
        const pong = {
          tag: BRIDGE_TAG,
          type: BRIDGE_PONG,
          nonce: data.nonce,
          ready: Boolean(monaco()),
        };
        window.postMessage(pong, window.location.origin);
        return;
      }

      if (data.type === BRIDGE_REQUEST) {
        window.postMessage(answer(data.nonce), window.location.origin);
      }
    });
  },
});