import { defineConfig } from "wxt";
import tailwindcss from "@tailwindcss/vite";

/**
 * The backend origin. It has to be known before any code runs because it
 * appears in `host_permissions`. WXT loads `.env` files into `process.env`
 * before this module evaluates.
 */
const API_BASE_URL =
  process.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ?? "https://api.codementor.example";

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