/* Catches case-insensitive filename collisions across the repository.
 *
 * Two files in one directory whose names differ only by case are two files on
 * Linux and ONE file on Windows and macOS. Nothing warns you at build time on
 * the machine that wrote the code, so the failure surfaces on a different
 * device, usually as a blank page:
 *
 *   UnsavedChanges.tsx   (the React context)
 *   unsavedChanges.ts    (the pure logic)
 *
 * An extensionless `from "./UnsavedChanges"` makes Vite probe extensions in
 * order -- .ts before .tsx -- so on a case-insensitive filesystem it resolved
 * to the logic module, which exports none of what the importer asked for. The
 * resulting SyntaxError killed the module graph before React mounted: white
 * page, no app. `forceConsistentCasingInFileNames` in tsconfig.json now makes
 * tsc catch the TypeScript side of this; this covers the rest of the tree,
 * including files TypeScript never resolves.
 *
 * Pairing a component with its own stylesheet (Foo.tsx + Foo.css) is fine --
 * those are imported with explicit extensions -- so this reports the pair as
 * information rather than pretending it is a defect, and only fails when the
 * pair would also be reachable extensionless.
 */
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const ROOT = "..";
const SKIP = new Set([
  ".git", "node_modules", "venv", "__pycache__", "dist",
  ".vite", "build", ".next", "coverage", ".pytest_cache",
]);

/** Extensions that are ever imported without one being typed out. */
const MODULE_EXT = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts"];
/** Extensions always written explicitly, so they cannot be resolved wrongly. */
const EXPLICIT_ONLY = new Set([".css", ".json", ".md", ".pdf", ".svg", ".png", ".jpg", ".txt", ".html"]);

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    if (SKIP.has(entry)) continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const files = walk(ROOT);

// Group by directory + lowercased basename-without-extension, which is the
// identity a case-insensitive filesystem actually uses.
const groups = new Map();
for (const file of files) {
  const dir = join(file, "..");
  const name = file.slice(dir.length + 1);
  const dot = name.lastIndexOf(".");
  const stem = (dot === -1 ? name : name.slice(0, dot)).toLowerCase();
  const ext = dot === -1 ? "" : name.slice(dot).toLowerCase();
  const key = `${dir}::${stem}`;
  if (!groups.has(key)) groups.set(key, []);
  groups.get(key).push({ name, ext });
}

const results = [];
const check = (name, cond, detail = "") =>
  results.push(`${cond ? "PASS" : "FAIL"} ${name}${detail ? ` -- ${detail}` : ""}`);

let collisions = 0;
let moduleAmbiguities = 0;

for (const [key, entries] of groups) {
  if (entries.length < 2) continue;
  collisions++;
  const dir = key.split("::")[0];
  const names = entries.map((e) => e.name).sort();

  const moduleLike = entries.filter((e) => MODULE_EXT.includes(e.ext));
  const ambiguous = moduleLike.length > 1;
  if (ambiguous) moduleAmbiguities++;

  const detail = `${names.join(" + ")}  (${relative(ROOT, dir)})`;
  check(
    ambiguous
      ? "MODULE EXTENSIONLESS AMBIGUITY"
      : "same-name non-module pair is fine",
    !ambiguous,
    detail
  );
}

check("no module-extensionless filename collisions", moduleAmbiguities === 0,
  moduleAmbiguities === 0
    ? `${collisions} same-name pair(s), all resolved by explicit extension`
    : `${moduleAmbiguities} need renaming`);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);