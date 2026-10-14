import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // The extraction and diagram code touch `DOMParser`, `document` and
    // `matchMedia`, so the jsdom environment is the honest one.
    environment: "jsdom",
    include: ["tests/**/*.test.ts"],
  },
});