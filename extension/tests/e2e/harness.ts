import { chromium, type BrowserContext } from "@playwright/test";
import { existsSync, mkdtempSync, readdirSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const EXTENSION_PATH = path.resolve(here, "../../.output/chrome-mv3");

function chromiumCandidates(root: string): string[] {
  if (!existsSync(root)) return [];
  return readdirSync(root)
    .filter((name) => /^chromium-\d+$/.test(name))
    .sort((a, b) => Number(b.slice("chromium-".length)) - Number(a.slice("chromium-".length)))
    .flatMap((name) => {
      const base = path.join(root, name);
      return [
        path.join(base, "chrome-win64", "chrome.exe"),
        path.join(base, "chrome-win", "chrome.exe"),
        path.join(base, "chrome-linux", "chrome"),
        path.join(base, "chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"),
      ];
    });
}

/**
 * The installed Playwright package and the browser cache can drift on an
 * offline machine. Prefer the browser Playwright expects, then use whatever
 * Chromium revision is actually on disk, then let Playwright fail normally.
 */
export function chromiumExecutable(): string | undefined {
  const override = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?.trim();
  if (override && existsSync(override)) return override;

  if (process.env.PLAYWRIGHT_BROWSERS_PATH?.trim()) {
    const found = chromiumCandidates(process.env.PLAYWRIGHT_BROWSERS_PATH).find(existsSync);
    if (found) return found;
  }

  const bundled = chromium.executablePath();
  if (existsSync(bundled)) return undefined;

  const localAppData = process.env.LOCALAPPDATA ?? path.join(homedir(), "AppData", "Local");
  const found = chromiumCandidates(path.join(localAppData, "ms-playwright")).find(existsSync);
  return found ?? undefined;
}

export type ExtensionContext = {
  context: BrowserContext;
  extensionId: string;
};

export async function launchExtension(): Promise<ExtensionContext> {
  if (!existsSync(EXTENSION_PATH)) {
    throw new Error(`Missing extension build at ${EXTENSION_PATH}. Run node tests/e2e/build-extension.mjs first.`);
  }

  const executablePath = chromiumExecutable();
  const userDataDir = mkdtempSync(path.join(tmpdir(), "codementor-e2e-"));
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: false,
    ...(executablePath ? { executablePath } : {}),
    args: [
      `--disable-extensions-except=${EXTENSION_PATH}`,
      `--load-extension=${EXTENSION_PATH}`,
      "--no-first-run",
      "--disable-default-apps",
    ],
    viewport: { width: 1280, height: 1000 },
  });

  const worker =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent("serviceworker", { timeout: 20_000 }));
  const extensionId = new URL(worker.url()).host;

  await worker.evaluate(
    () =>
      new Promise<void>((resolve) => {
        chrome.storage.local.set(
          {
            auth: {
              accessToken: "e2e-token",
              refreshToken: null,
              expiresAt: null,
            },
          },
          () => resolve(),
        );
      }),
  );

  return { context, extensionId };
}

export async function fakeState(): Promise<Record<string, unknown>> {
  const base = process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:8787";
  const res = await fetch(`${base}/__state`);
  if (!res.ok) throw new Error(`Fake API state failed: ${res.status}`);
  return (await res.json()) as Record<string, unknown>;
}
