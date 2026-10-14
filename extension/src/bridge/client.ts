/**
 * Content-script side of the editor bridge (§5.4).
 *
 * Talks to `bridge.content.ts` over `window.postMessage`, matching replies by
 * nonce so a late answer from a previous request is ignored.
 */

import { uuid } from "../lib/async";
import {
  BRIDGE_PING,
  BRIDGE_PONG,
  BRIDGE_REQUEST,
  BRIDGE_TAG,
  BRIDGE_TIMEOUT_MS,
  isBridgeResponse,
  type BridgeResponse,
} from "./protocol";

export type EditorBuffer = {
  code: string;
  languageId: string;
  ambiguous: boolean;
  via: BridgeResponse["via"];
  /** True when the buffer came from the DOM fallback rather than Monaco. */
  lossy: boolean;
};

const NO_BUFFER: EditorBuffer = {
  code: "",
  languageId: "",
  ambiguous: false,
  via: "none",
  lossy: false,
};

function request(type: typeof BRIDGE_REQUEST | typeof BRIDGE_PING, nonce: string): void {
  window.postMessage({ tag: BRIDGE_TAG, type, nonce }, window.location.origin);
}

/** Wait until the page has loaded `monaco`. Resolves false on timeout. */
export async function waitForBridge(timeoutMs = BRIDGE_TIMEOUT_MS): Promise<boolean> {
  const nonce = uuid();
  return new Promise<boolean>((resolve) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(false);
    }, timeoutMs);

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return;
      const data = event.data as { tag?: string; type?: string; nonce?: string; ready?: boolean };
      if (data?.tag !== BRIDGE_TAG || data.type !== BRIDGE_PONG || data.nonce !== nonce) return;
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      resolve(Boolean(data.ready));
    }

    window.addEventListener("message", onMessage);
    request(BRIDGE_PING, nonce);
  });
}

/**
 * Read the learner's current buffer.
 *
 * Returns `null` when the bridge cannot reach Monaco at all, so the caller can
 * fall back to the editor's textarea and then to "paste your code here".
 */
export function readEditorBuffer(timeoutMs = BRIDGE_TIMEOUT_MS): Promise<EditorBuffer | null> {
  const nonce = uuid();
  return new Promise<EditorBuffer | null>((resolve) => {
    const timer = setTimeout(() => {
      window.removeEventListener("message", onMessage);
      resolve(null);
    }, timeoutMs);

    function onMessage(event: MessageEvent) {
      if (event.source !== window) return;
      if (!isBridgeResponse(event.data)) return;
      if (event.data.nonce !== nonce) return;
      clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      const { code, languageId, ambiguous, via } = event.data;
      if (via === "none") {
        resolve(null);
        return;
      }
      resolve({ code, languageId, ambiguous, via, lossy: via === "dom_scrape" });
    }

    window.addEventListener("message", onMessage);
    request(BRIDGE_REQUEST, nonce);
  });
}

/**
 * Fallback (a) from §5.4: the editor's hidden textarea, which Monaco keeps in
 * sync for accessibility and IME. Lossy for multi-line buffers, so it is only
 * used when the bridge is unavailable.
 */
export function readEditorTextarea(): EditorBuffer {
  const textarea = document.querySelector<HTMLTextAreaElement>(
    ".monaco-editor textarea, textarea.inputarea",
  );
  const value = textarea?.value?.trim() ?? "";
  return value ? { ...NO_BUFFER, code: value, ambiguous: true, lossy: true } : NO_BUFFER;
}

/** Bridge first, textarea second, `null` when neither has content. */
export async function readBufferOrFallback(): Promise<EditorBuffer | null> {
  const fromBridge = await readEditorBuffer();
  if (fromBridge?.code.trim()) return fromBridge;
  const fromTextarea = readEditorTextarea();
  return fromTextarea.code.trim() ? fromTextarea : null;
}