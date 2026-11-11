/**
 * The typed contract between the always-on content script and the on-demand
 * overlay script.
 *
 * Both run in the extension's isolated world, so they hand data over through
 * `window` rather than a channel. Declaring that surface once keeps the two
 * entrypoints from drifting apart, and keeps the untyped globals from spreading.
 */

import type { ProblemData } from "../schemas";

export type ProblemBridge = {
  slug: string;
  problem: ProblemData | null;
  note: string | null;
};

export type OverlayHandle = {
  unmount: () => void;
  setProblem: (slug: string, problem: ProblemData | null, note: string | null) => void;
  focus: () => void;
};

export type DebugHelpers = Record<string, (...args: any[]) => unknown>;

declare global {
  interface Window {
    __codementorProblem?: ProblemBridge;
    __codementorUi?: OverlayHandle;
    __codementorRemoveLauncher?: () => void;
    __codementorShowLauncher?: () => void;
    __codementorDebug?: DebugHelpers;
  }
}
