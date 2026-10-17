/* Runner for the jsdom smoke tests.
 *
 * These scripts import .tsx modules directly, which bare node refuses
 * (ERR_UNKNOWN_FILE_EXTENSION). Vite is already a dev dependency and knows
 * how to load TSX, so this provides the loader the tests were already written
 * against - it does not change any test's assertions.
 *
 * Usage: node run-smoke.mjs <script.mjs>
 */
import { createServer } from "vite";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const target = process.argv[2];

if (!target) {
  console.error("usage: node run-smoke.mjs <script.mjs>");
  process.exit(2);
}

const server = await createServer({
  root: here,
  logLevel: "error",
  server: { middlewareMode: true },
  appType: "custom",
  // src/config.ts holds `import.meta` in a variable and reads
  // `meta.env.VITE_*`. That is correct app code -- the browser build inlines
  // it -- but Vite's SSR runner throws on dynamic `import.meta.env` access.
  // Handing it a concrete object lets the module evaluate under the harness
  // without changing anything the app ships.
  define: {
    "import.meta.env": JSON.stringify({
      VITE_API_BASE_URL: process.env.VITE_API_BASE_URL ?? "",
      VITE_APP_ENV: process.env.VITE_APP_ENV ?? "test",
      VITE_FORCE_HTTPS: process.env.VITE_FORCE_HTTPS ?? "false",
      MODE: "test",
      DEV: false,
      PROD: false,
      SSR: true,
    }),
  },
});

let failed = 1;
try {
  await server.ssrLoadModule(path.resolve(here, target));
  failed = 0;
} finally {
  await server.close();
  // The smoke scripts call process.exit themselves on failure; if one threw
  // before reaching that, surface it as a non-zero exit.
  process.exit(failed);
}
