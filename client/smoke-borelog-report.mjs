/* Live smoke test for the Field Data → Overview borelog report.
 *
 * Mounts BorelogReportPreview in jsdom against a REAL running server -- no
 * mocked fetch, no mocked rows -- so it proves the whole chain in one go: the
 * JSON contract the client expects, the continuous table rendering, and the
 * full depth arriving as one scrollable body rather than a page per 20 m.
 *
 * Usage (apiClient resolves its origin at module load, so the origin has to be
 * in the environment before Vite starts):
 *
 *   cd server && ./venv/bin/python -m uvicorn app.main:app --port 8000
 *   cd client
 *   VITE_API_BASE_URL=http://127.0.0.1:8000 \
 *   VITE_SMOKE_TOKEN=<access token> node smoke-borelog-report.mjs
 *
 * SMOKE_PROJECT / SMOKE_LOCA choose the borehole (defaults below).
 */
import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { createServer } from "vite";

const here = path.dirname(fileURLToPath(import.meta.url));
const API = (process.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const TOKEN = process.env.VITE_SMOKE_TOKEN ?? "";
const PROJECT = process.env.SMOKE_PROJECT ?? "TDAC-2026-09-901";
const LOCA = process.env.SMOKE_LOCA ?? "BH-1";

if (!API || !TOKEN) {
  console.error(
    "VITE_API_BASE_URL and VITE_SMOKE_TOKEN must both be set; see the header of this file.",
  );
  process.exit(2);
}

// jsdom is not a project dependency, and the existing jsdom smoke tests
// (smoke-workspace, smoke-modal, smoke-spt-verify) already assume it is
// resolvable without declaring it. Look in node_modules, then walk up the
// directory tree, so this script works wherever those do instead of failing
// for a different reason.
function loadJsdom() {
  const require = createRequire(import.meta.url);
  try {
    return require("jsdom").JSDOM;
  } catch {
    // fall through to the search below
  }

  let dir = here;
  while (true) {
    const candidate = path.join(dir, "node_modules", "jsdom");
    if (existsSync(candidate)) {
      return createRequire(path.join(candidate, "index.js"))("jsdom").JSDOM;
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }

  console.error(
    "jsdom is not installed. The other jsdom smoke tests need it too:\n" +
      "  npm i -D jsdom",
  );
  process.exit(2);
}

const JSDOM = loadJsdom();

const dom = new JSDOM(
  "<!doctype html><html><body><div id=root></div></body></html>",
  { url: "http://localhost/", pretendToBeVisual: true },
);
globalThis.window = dom.window;
globalThis.document = dom.window.document;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// apiClient reads the session token from localStorage under this key; see
// src/api/token.ts. Nothing is faked, so the request must really authenticate.
globalThis.localStorage = {
  getItem: (key) => (key === "access_token" ? TOKEN : null),
  setItem: () => {},
  removeItem: () => {},
};

const vite = await createServer({
  root: here,
  logLevel: "error",
  server: { middlewareMode: true },
  appType: "custom",
  plugins: [
    {
      /*
       * src/config.ts reads `import.meta.env` dynamically, which Vite 8's SSR
       * module runner refuses. Transform that one line into a plain object:
       * by this hook Vite has already stripped the types, so the source is
       * `const meta = import.meta;`. Nothing in src/ is edited.
       */
      name: "config-env-shim",
      transform(code, id) {
        if (!id.endsWith("/src/config.ts")) return null;
        return code.replace(
          /const meta = [^;]*;/,
          `const meta = { env: ${JSON.stringify({ VITE_API_BASE_URL: API })} };`,
        );
      },
    },
  ],
});

const { BorelogReportPreview } = await vite.ssrLoadModule(
  path.resolve(here, "src/pages/ProjectWorkspace/FieldData/BorelogReportPreview.tsx"),
);

const results = [];
function check(name, fn) {
  try {
    fn();
    results.push(`PASS ${name}`);
  } catch (err) {
    results.push(`FAIL ${name} -> ${err.message}`);
  }
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const root = createRoot(document.getElementById("root"));

await act(async () => {
  root.render(
    React.createElement(BorelogReportPreview, {
      projectId: PROJECT,
      locaId: LOCA,
    }),
  );
});
await act(async () => {
  await new Promise((resolve) => setTimeout(resolve, 1500));
});

const el = document.getElementById("root");
const data_layers = () =>
  report.layers ?? report.rows.filter((row) => row.kind === "layer");

const report = await fetch(
  `${API}/api/portfolio/projects/${PROJECT}/locas/${LOCA}/borelog-report`,
  { headers: { Authorization: `Bearer ${TOKEN}` } },
).then((response) => response.json());

check("the report loaded from the real API", () => {
  assert(report.rows?.length > 0, "the API returned no rows");
  assert(
    !el.querySelector(".field-error"),
    `the component reported an error: ${el.querySelector(".field-error")?.textContent}`,
  );
});

check("the report title block is rendered", () => {
  const title = el.querySelector(".borelog-report-title");
  assert(title, "no title block");
  assert(
    title.textContent.includes("GEOTECHNICAL INVESTIGATION FOR THE PROPOSED"),
    `title reads: ${title.textContent}`,
  );
});

check("every header field is rendered", () => {
  for (const label of [
    "Client",
    "Borehole No",
    "Type of Boring",
    "Termination Depth",
    "Boring Start Date",
    "Completion Date",
    "Ground Water Table",
    "Location",
  ]) {
    assert(el.textContent.includes(label), `header field missing: ${label}`);
  }
  assert(
    el.textContent.includes(report.header.borehole_number),
    "borehole number not shown",
  );
});

check("Generate PDF button is present and enabled", () => {
  const button = [...el.querySelectorAll("button")].find(
    (node) => node.textContent.trim() === "Generate PDF",
  );
  assert(button, "no Generate PDF button");
  assert(!button.disabled, "the button is disabled with data present");
});

check("the summary chip beside the button is gone", () => {
  assert(
    !el.querySelector(".chip"),
    "a summary chip is still rendered beside Generate PDF",
  );
  assert(
    !el.textContent.includes("in PDF"),
    "the PDF page count is still shown in the header",
  );
});

check("the note reads as the continuous log, with live counts", () => {
  const note = el.querySelector(".borelog-report-note");
  assert(note, "no note under the header");
  assert(
    note.textContent.includes("Continuous log for the full depth."),
    `note reads: ${note.textContent}`,
  );

  // The counts must come from the payload, not be hard-coded.
  const counts = note.querySelector(".borelog-report-counts");
  assert(counts, "the counts are not in their own element");
  // "SPT" is an abbreviation, not a countable noun, so it is never pluralised.
  const expected =
    `${report.summary.layer_count} layer${report.summary.layer_count === 1 ? "" : "s"}` +
    (report.summary.spt_count > 0 ? ` · ${report.summary.spt_count} SPT` : "");
  assert(
    counts.textContent.trim() === expected,
    `counts read "${counts.textContent}", expected "${expected}"`,
  );
});

check("every column header is rendered, in order", () => {
  // The scale gutter leads: it is a reference axis, not a record column, so it
  // carries only its unit.
  const expected = [
    "m",
    "Depth (m)",
    "Soil Profile",
    "Description",
    "Thickness",
    "SPT Depth",
    "15 cm",
    "30 cm",
    "45 cm",
    "SPT N-Value",
    "SPT Plot",
  ];
  const rendered = [...el.querySelectorAll(".borelog-column-header")].map(
    (node) => node.textContent.trim(),
  );
  assert(
    rendered.join("|") === expected.join("|"),
    `columns read ${rendered.join(" | ")}`,
  );
});

check("the 0.00 tick is fully visible", () => {
  // The axis label at depth 0 is centred on the log's own top edge, so half of
  // it sits above the log. Without room for it the scroll container clips it and
  // the log appears to start below 0.00.
  const first = el.querySelector(".borelog-depth-tick");
  assert(first, "no depth ticks at all");
  assert(
    first.textContent.trim() === "0.00",
    `the first tick reads ${first.textContent}, expected 0.00`,
  );

  const scroll = el.querySelector(".borelog-report-scroll");
  const tickTop = first.getBoundingClientRect().top;
  assert(
    tickTop >= scroll.getBoundingClientRect().top - 0.5,
    "the 0.00 tick is clipped by the top of the scroll region",
  );
});

check("the log starts exactly at depth 0", () => {
  // The band above the log exists only so the 0.00 label has room; the first
  // stratum must still begin at 0%, not below it.
  const first = el.querySelector(".borelog-profile-bar");
  assert(first, "no strata drawn");
  assert(
    Math.abs(parseFloat(first.style.top)) < 0.01,
    `the first stratum starts at ${first.style.top}, expected 0%`,
  );
  const depthZero = data_layers()[0];
  assert(
    depthZero.depth_from === 0,
    `the first stratum starts at ${depthZero.depth_from} m`,
  );
});

check("the log is one continuous depth-proportional block", () => {
  assert(el.querySelector(".borelog-log"), "no log body");
  assert(
    !el.querySelector("table"),
    "the log is rendered as a table again, not as depth-proportional columns",
  );

  // The log's height is computed from total depth, not fixed by a row count.
  // The body is one termination band taller: the note is centred on the base of
  // the hole and hangs half below it, as it does on the sheet.
  const height = parseFloat(el.querySelector(".borelog-log").style.height);
  assert(height > 0, `log height reads ${height}`);
  const expected = Math.max(report.header.termination_depth * 30, 460);
  assert(
    Math.abs(height - expected) < 1,
    `log height ${height}, expected about ${expected}`,
  );

  const bodyHeight = parseFloat(
    el.querySelector(".borelog-body").style.height,
  );
  assert(
    bodyHeight > height,
    `the body (${bodyHeight}) must be taller than the log (${height}) to leave room for the note`,
  );

  // The axis must describe the same depths as the log: same height, or the
  // ticks and the strata would disagree about where 10 m is.
  const scaleHeight = parseFloat(
    el.querySelector(".borelog-scale").style.height,
  );
  assert(
    Math.abs(scaleHeight - height) < 0.5,
    `the scale is ${scaleHeight} but the log is ${height}`,
  );

  // Only meaningful on a borehole deep enough to span pages; a shallow one is
  // legitimately a single page and must not fail this check.
  if (report.pdf_page_count > 1) {
    assert(
      el.querySelectorAll(".borelog-log").length === 1,
      "the preview was split into pages",
    );
  }
});

check("column widths match the PDF's, from the server", () => {
  const columns = el.querySelectorAll(".borelog-col");
  // Ten columns: depth, profile, description, thickness, spt_depth, 3 blow
  // counts, n_value, spt_plot.
  assert(
    columns.length === 10,
    `expected 10 columns, found ${columns.length}`,
  );

  const byPercent = report.columns.map((column) => column.percent);
  const rendered = [...columns].map((node) =>
    Number.parseFloat(node.style.flex),
  );
  assert(
    rendered.join(",") === byPercent.join(","),
    `widths read ${rendered.join(",")}, expected ${byPercent.join(",")}`,
  );
});

check("it scrolls in one region", () => {
  assert(
    el.querySelector(".borelog-report-scroll"),
    "no scroll container around the log",
  );
});

check("strata are drawn to their real thickness", () => {
  const bars = [...el.querySelectorAll(".borelog-profile-bar")];
  assert(
    bars.length === report.layers.length,
    `drawn ${bars.length} strata for ${report.layers.length}`,
  );

  // The first two strata must differ in height in proportion to thickness --
  // this is the whole difference between a log and a list of records.
  const [first, second] = report.layers;
  if (first && second && second.thickness > first.thickness) {
    const firstPct = parseFloat(bars[0].style.height);
    const secondPct = parseFloat(bars[1].style.height);
    assert(
      secondPct > firstPct,
      `a ${second.thickness} m stratum is drawn no taller than a ${first.thickness} m one`,
    );
  }

  // Each bar's top must be its own depth, as a share of the total.
  const maxDepth = report.header.termination_depth;
  bars.forEach((bar, index) => {
    const expected =
      ((report.layers[index].depth_from ?? 0) / maxDepth) * 100;
    assert(
      Math.abs(parseFloat(bar.style.top) - expected) < 0.01,
      `stratum ${index} drawn at ${bar.style.top}, expected ${expected}%`,
    );
  });
});

check("every stratum description reached the DOM", () => {
  assert(report.layers.length > 0, "the borehole has no strata to render");
  const cells = el.querySelectorAll(".borelog-description-cell");
  assert(
    cells.length === report.layers.length,
    `drawn ${cells.length} descriptions for ${report.layers.length} strata`,
  );
  for (const layer of report.layers) {
    if (!layer.description) continue;
    assert(
      el.textContent.includes(layer.description.slice(0, 24)),
      `description missing from the DOM: ${layer.description}`,
    );
  }
});

check("SPT tests sit at the base of their drive", () => {
  assert(report.spt.length > 0, "the borehole has no SPT to render");
  const markers = [...el.querySelectorAll(".borelog-spt-marker")];
  assert(
    markers.length === report.spt.length * 5,
    `drawn ${markers.length} SPT markers for ${report.spt.length} tests across five columns`,
  );

  for (const test of report.spt) {
    assert(
      el.textContent.includes(test.spt_depth_text),
      `SPT depth missing: ${test.spt_depth_text}`,
    );
    assert(
      el.textContent.includes(test.n_text),
      `N-value missing: ${test.n_text}`,
    );
  }

  // The plot column carries one dot per driven test.
  assert(
    el.querySelectorAll(".borelog-plot-dot").length ===
      report.spt.filter((test) => test.n_plot_fraction !== null).length,
    "plot dots do not match the SPT tests",
  );
});

check("soil profile hatches vary between strata", () => {
  const hatches = new Set(
    [...el.querySelectorAll(".borelog-profile-bar")].map(
      (node) => node.className,
    ),
  );
  const soils = report.layers.filter((layer) => !layer.is_rock);
  assert(soils.length > 1, "not enough soil strata to tell apart");
  assert(hatches.size >= 2, "every stratum looks the same");
});

check("the water table rule is drawn at its depth", () => {
  const marker = el.querySelector(".borelog-water-table");
  if (report.header.water_table === null) {
    assert(!marker, "a water table rule appeared with no water table");
    return;
  }
  assert(marker, "water table rule missing");
  assert(
    marker.textContent.includes(
      `Water Table at ${report.header.water_table.toFixed(2)} m`,
    ),
    `rule reads: ${marker.textContent}`,
  );
  const expected =
    (report.header.water_table / report.header.termination_depth) * 100;
  assert(
    Math.abs(parseFloat(marker.style.top) - expected) < 0.01,
    `water table drawn at ${marker.style.top}, expected ${expected}%`,
  );
});

check("the termination note closes the log", () => {
  const marker = el.querySelector(".borelog-termination");
  assert(marker, "termination note missing");
  assert(
    marker.textContent.includes(
      `TERMINATED AT ${report.header.termination_depth.toFixed(2)} m DEPTH`,
    ),
    `note reads: ${marker.textContent}`,
  );
});

console.log(results.join("\n"));
const failed = results.filter((result) => result.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} passed`);

root.unmount();
await vite.close();

if (failed.length > 0) {
  process.exit(1);
}
