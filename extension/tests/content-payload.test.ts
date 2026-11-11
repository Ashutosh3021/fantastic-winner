import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The overlay was moved out of the always-on content script because bundling
 * React and the cards there cost ~207 ms of main-thread evaluation on every
 * problem page (337 ms -> 130 ms). Keep it that way: this entrypoint must stay
 * a thin extractor, and the UI must only enter through `overlay-ui.tsx`.
 */
describe("content script payload budget", () => {
  const source = readFileSync(
    path.resolve(process.cwd(), "entrypoints/content.tsx"),
    "utf8",
  );

  it("does not import React", () => {
    expect(source).not.toMatch(/from\s+["']react/);
    expect(source).not.toMatch(/from\s+["']react-dom/);
  });

  it("does not import the overlay or its cards", () => {
    expect(source).not.toMatch(/from\s+["'][^"']*\/ui\/overlay["']/);
    expect(source).not.toMatch(/from\s+["'][^"']*\/ui\/cards/);
    expect(source).not.toMatch(/createRoot/);
  });
});
