import { defineConfig } from "wxt";
import tailwindcss from "@tailwindcss/vite";
import { readFileSync } from "node:fs";

/**
 * Read `.env` ourselves rather than relying on WXT to have done it.
 *
 * This module is evaluated before Vite loads any `.env*` file, and
 * `host_permissions` is baked into the manifest from a value read here — so if
 * the variable is not in `process.env` at this point the manifest silently
 * ships the placeholder origin and Chrome blocks every request to the real
 * backend. Reading it directly removes that dependency.
 */
function envFromFile(path: string, variable: string, fallback: string): string {
  const fromProcess = process.env[variable]?.trim().replace(/\/+$/, "");
  if (fromProcess) return fromProcess;
  try {
    const raw = readFileSync(path, "utf8");
    const match = raw.match(new RegExp(`^${variable}=(.*)$`, "m"));
    const value = match?.[1]?.trim().replace(/\/+$/, "");
    return value && value.length > 0 ? value : fallback;
  } catch {
    return fallback;
  }
}

const PLACEHOLDER_API_BASE_URL = "https://api.codementor.example";

/**
 * The backend origin. It has to be known before any code runs because it
 * appears in `host_permissions`.
 */
const API_BASE_URL = envFromFile(
  ".env",
  "VITE_API_BASE_URL",
  PLACEHOLDER_API_BASE_URL,
);

// A production build aimed at the placeholder cannot reach a real backend, and
// the failure otherwise appears much later as a Chrome host-permission error.
// Dev builds may keep the fallback so the UI can be worked on without a server.
if (process.env.NODE_ENV === "production" && API_BASE_URL === PLACEHOLDER_API_BASE_URL) {
  throw new Error(
    "VITE_API_BASE_URL is still the placeholder. Create extension/.env from .env.example before a production build.",
  );
}

/**
 * Login flow for the Pyronites account system.
 *
 * - `hosted` — the backend serves the page and hands back a one-time code the
 *   popup exchanges for tokens. Requires no extra permission.
 * - `webext` — `chrome.identity.launchWebAuthFlow` against an OAuth provider.
 *   Requires the `identity` permission, so it is only requested when selected.
 */
const AUTH_FLOW = (process.env.VITE_AUTH_FLOW ?? "hosted") as "hosted" | "webext";

export default defineConfig({
  srcDir: ".",
  modules: ["@wxt-dev/module-react"],

  manifest: {
    name: "CodeMentor",
    short_name: "CodeMentor",
    description:
      "A step-by-step thinking coach for LeetCode. Learn the concept first, answer a few small questions, then write the solution yourself.",
    version: "0.1.0",
    // No `default_locale`: there are no translated strings, and declaring one
    // without a `_locales` subtree makes Chrome refuse to load the extension
    // ("Default locale was specified, but _locales subtree is missing").

    permissions: [
      "storage",
      ...(AUTH_FLOW === "webext" ? (["identity"] as const) : []),
    ],

    host_permissions: ["https://leetcode.com/*", `${API_BASE_URL}/*`],

    web_accessible_resources: [
      {
        resources: ["fonts/*"],
        matches: ["https://leetcode.com/*"],
      },
    ],
  },

  vite: () => ({
    plugins: [tailwindcss()],
    build: { target: "chrome120" },
  }),
});