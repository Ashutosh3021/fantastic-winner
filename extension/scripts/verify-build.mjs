/*
 * Fail the production build if the API origin baked into the bundle is not the
 * one the manifest advertises.
 *
 * The E2E harness used to build into `.output` with a localhost API origin, so
 * running the tests after a real build silently replaced the shippable bundle
 * with one that could not reach the backend. Keep the two facts tied together:
 * the `.env`/`process.env` origin and the origin compiled into `background.js`.
 */

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outDir = process.env.WXT_OUT_DIR?.trim() || ".output";
const dist = path.join(root, outDir, "chrome-mv3");

function fail(message) {
  console.error(`[verify-build] ${message}`);
  process.exit(1);
}

function envFromFile(variable) {
  try {
    const raw = readFileSync(path.join(root, ".env"), "utf8");
    return raw.match(new RegExp(`^${variable}=(.*)$`, "m"))?.[1]?.trim() ?? "";
  } catch {
    return "";
  }
}

const expected = (process.env.VITE_API_BASE_URL?.trim() || envFromFile("VITE_API_BASE_URL")).replace(
  /\/+$/,
  "",
);

if (!expected) fail("VITE_API_BASE_URL is not set in the environment or .env.");
if (expected.endsWith("codementor.example")) fail(`refusing to ship the placeholder origin: ${expected}`);
if (/^https?:\/\/(127\.0\.0\.1|localhost)(:|\/|$)/.test(expected)) {
  fail(`refusing to ship a loopback API origin: ${expected}`);
}

const backgroundPath = path.join(dist, "background.js");
if (!existsSync(backgroundPath)) fail(`missing ${backgroundPath}; run a production build.`);
const background = readFileSync(backgroundPath, "utf8");

const baked = background.match(/VITE_API_BASE_URL:\s*([`"'])(.*?)\1/)?.[2];
if (baked !== expected) {
  fail(`bundle bakes VITE_API_BASE_URL=${JSON.stringify(baked)}, expected ${JSON.stringify(expected)}.`);
}

const manifest = JSON.parse(readFileSync(path.join(dist, "manifest.json"), "utf8"));
const hosts = manifest.host_permissions ?? [];
if (!hosts.includes(`${expected}/*`)) {
  fail(`manifest host_permissions does not include ${expected}/*.`);
}

for (const asset of ["overlay-ui.js", "assets/overlay-styles.css"]) {
  if (!existsSync(path.join(dist, asset))) fail(`missing build asset: ${asset}`);
}

console.log(`[verify-build] ok: ${expected}`);
