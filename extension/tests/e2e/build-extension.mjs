import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "../..");
const wxt = path.join(root, "node_modules", "wxt", "bin", "wxt.mjs");

const result = spawnSync(process.execPath, [wxt, "build"], {
  cwd: root,
  stdio: "inherit",
  env: {
    ...process.env,
    NODE_ENV: "production",
    VITE_API_BASE_URL: process.env.E2E_API_BASE_URL ?? "http://127.0.0.1:8787",
  },
});

if (result.error) throw result.error;
process.exit(result.status ?? 1);
