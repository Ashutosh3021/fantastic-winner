/** Messages exchanged between the content script and the MAIN-world bridge (§5.4). */

export const BRIDGE_TAG = "codementor";
export const BRIDGE_REQUEST = "CM_GET_CODE";
export const BRIDGE_RESPONSE = "CM_CODE";
export const BRIDGE_PING = "CM_PING";
export const BRIDGE_PONG = "CM_PONG";

/** How long the content script waits for the bridge before using a fallback. */
export const BRIDGE_TIMEOUT_MS = 3_000;

export type BridgeVia =
  | "focused_editor"
  | "visible_editor"
  | "uri_match"
  | "dom_scrape"
  | "none";

export type BridgeRequest = {
  tag: typeof BRIDGE_TAG;
  type: typeof BRIDGE_REQUEST;
  nonce: string;
};

export type BridgeResponse = {
  tag: typeof BRIDGE_TAG;
  type: typeof BRIDGE_RESPONSE;
  nonce: string;
  code: string;
  languageId: string;
  /**
   * True when more than one editor buffer existed and we could not prove which
   * one is the learner's. The UI asks instead of guessing.
   */
  ambiguous: boolean;
  /** How the answer was obtained. Debug/telemetry only. */
  via: BridgeVia;
};

export type BridgePing = {
  tag: typeof BRIDGE_TAG;
  type: typeof BRIDGE_PING;
  nonce: string;
};

export type BridgePong = {
  tag: typeof BRIDGE_TAG;
  type: typeof BRIDGE_PONG;
  nonce: string;
  ready: boolean;
};

function hasTag(value: unknown): value is { tag: string; type: string; nonce: string } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return candidate.tag === BRIDGE_TAG && typeof candidate.type === "string" &&
    typeof candidate.nonce === "string";
}

export function isBridgeResponse(value: unknown): value is BridgeResponse {
  return hasTag(value) && value.type === BRIDGE_RESPONSE && typeof (value as BridgeResponse).code === "string";
}

export function isBridgePong(value: unknown): value is BridgePong {
  return hasTag(value) && value.type === BRIDGE_PONG;
}