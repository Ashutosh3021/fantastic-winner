import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const playwright = path.join(root, "node_modules", "@playwright", "test", "cli.js");

// Shared with `build-extension.mjs` and `harness.ts`; the build and the browser
// must look at the same directory, and it must not be the shippable `.output`.
process.env.WXT_OUT_DIR ??= ".output-e2e";

const build = spawnSync(process.execPath, [path.join(here, "build-extension.mjs")], {
  cwd: root,
  stdio: "inherit",
});
if (build.error) throw build.error;
if (build.status !== 0) process.exit(build.status ?? 1);

const args = [playwright, "test", ...process.argv.slice(2)];
const result = spawnSync(process.execPath, args, {
  cwd: root,
  stdio: "inherit",
  env: process.env,
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
