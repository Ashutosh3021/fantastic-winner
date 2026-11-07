import { storage } from "wxt/utils/storage";
import type { DifficultyMode, Language, Preferences, Theme } from "../schemas";

/**
 * Preferences.
 *
 * The backend owns the truth (`user_preferences.prefs_version`). The extension
 * keeps a copy for instant render and revalidates it whenever the overlay is
 * opened, which is what stops a learner who switched to Hindi from getting an
 * English overlay against Hindi backend content (§5.6).
 */

export const prefsStore = storage.defineItem<Preferences>("local:prefs", {
  fallback: {
    language: "en",
    difficulty_mode: "beginner",
    theme: "system",
    timezone: "UTC",
    prefs_version: 0,
  },
  version: 1,
});

/** Mirrors the server's `prefs_version` so the worker can flag staleness cheaply. */
export const prefsVersionStore = storage.defineItem<number>("local:prefs:version", {
  fallback: 0,
  version: 1,
});

/** UI-only overlay state, persisted per problem slug (§5.6). */
export type OverlayUiState = {
  collapsed: boolean;
  /** Legacy global flag, kept so an older stored value still reads. */
  checklistRevealed: boolean;
  checklistRevealedBySlug?: Record<string, boolean>;
  lastSlug: string;
};

export const overlayStateStore = storage.defineItem<OverlayUiState>("local:ui", {
  fallback: {
    collapsed: false,
    checklistRevealed: false,
    checklistRevealedBySlug: {},
    lastSlug: "",
  },
  version: 1,
});

export async function setPrefs(next: Partial<Preferences>): Promise<Preferences> {
  const current = await prefsStore.getValue();
  const merged = { ...current, ...next };
  await prefsStore.setValue(merged);
  await prefsVersionStore.setValue(merged.prefs_version);
  return merged;
}

/** Persist a partial UI-state change without clobbering the rest. */
export async function patchOverlayState(patch: Partial<OverlayUiState>): Promise<void> {
  const current = await overlayStateStore.getValue();
  await overlayStateStore.setValue({ ...current, ...patch });
}

/** Remember whether the earned checklist was opened, per problem slug. */
export async function setChecklistRevealed(slug: string, revealed: boolean): Promise<void> {
  const current = await overlayStateStore.getValue();
  await overlayStateStore.setValue({
    ...current,
    checklistRevealed: revealed,
    checklistRevealedBySlug: {
      ...(current.checklistRevealedBySlug ?? {}),
      [slug]: revealed,
    },
    lastSlug: slug,
  });
}

/** Server time is authoritative (§16.5); the client only formats the label. */
export function formatResetTime(iso: string, timezone: string): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
      timeZone: timezone,
    }).format(new Date(iso));
  } catch {
    return new Date(iso).toLocaleTimeString();
  }
}

export function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function resolveTheme(theme: Theme): boolean {
  if (theme === "dark") return true;
  if (theme === "light") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export type { DifficultyMode, Language, Theme };