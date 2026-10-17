/* Live smoke test: Lab Data > Sample Register.
 *
 * Drives the real tab in jsdom against a running server -- no mocked fetch --
 * so it covers the things server tests cannot: that the project-scoped register
 * lists every borehole, that narrowing to one location is done in the query
 * rather than in the browser, and that the Location column appears and
 * disappears correctly.
 *
 * Needs a project that has at least one approved Soil (SPT) record, so that a
 * location can actually be narrowed to. Everything else is derived from the
 * API at run time, so it works against any database.
 *
 *   cd server && ./venv/bin/python -m uvicorn app.main:app --port 8000
 *   cd client
 *   VITE_API_BASE_URL=http://127.0.0.1:8000 \
 *   VITE_SMOKE_TOKEN=<access token> \
 *   SMOKE_PROJECT=<project id> node smoke-sample-register.mjs
 */
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";

const here = path.dirname(fileURLToPath(import.meta.url));
const { JSDOM } = createRequire(import.meta.url)("jsdom");

const API = process.env.VITE_API_BASE_URL;
const TOKEN = process.env.VITE_SMOKE_TOKEN;
const PROJECT = process.env.SMOKE_PROJECT;

if (!API || !TOKEN || !PROJECT) {
  console.error(
    "VITE_API_BASE_URL, VITE_SMOKE_TOKEN and SMOKE_PROJECT are all required."
  );
  process.exit(2);
}

const auth = () => ({ headers: { Authorization: `Bearer ${TOKEN}` } });
const getJson = async (p) => {
  const r = await fetch(`${API}${p}`, auth());
  if (!r.ok) throw new Error(`${p} -> ${r.status}`);
  return r.json();
};

// What the server says is there, so nothing below is hardcoded to one database.
const [locasPayload, register] = await Promise.all([
  getJson(`/api/portfolio/projects/${PROJECT}/locas`),
  getJson(`/api/portfolio/projects/${PROJECT}/sample-register`),
]);

const locaIds = [...new Set(locasPayload.locas.map((l) => l.loca_id))].sort();
const soilLocaIds = [...new Set(register.soil.map((r) => r.loca_id))].sort();

if (soilLocaIds.length < 2) {
  console.error(
    `SMOKE_PROJECT ${PROJECT} has approved Soil for only ` +
      `${soilLocaIds.length} borehole(s) (${soilLocaIds.join(", ") || "none"}).\n` +
      `The Sample Register is project-scoped, so this test needs at least two ` +
      `boreholes to prove the register spans the project and that the ` +
      `Location filter narrows it. Point it at a project with approved SPT ` +
      `data in two or more boreholes.`
  );
  process.exit(2);
}

const target = soilLocaIds[0];
const targetParam = encodeURIComponent(target);
const expected = register.soil.filter((r) => r.loca_id === target);

const dom = new JSDOM(
  "<!doctype html><html><body><div id=root></div></body></html>",
  { url: "http://localhost/", pretendToBeVisual: true }
);
global.window = dom.window;
global.document = dom.window.document;
global.HTMLElement = dom.window.HTMLElement;
global.Node = dom.window.Node;
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
global.IS_REACT_ACT_ENVIRONMENT = true;
global.localStorage = {
  getItem: (k) => (k === "access_token" ? TOKEN : null),
  setItem() {},
  removeItem() {},
};

const seen = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (u, o) => {
  seen.push(String(u));
  return realFetch(u, o);
};

const vite = await createServer({
  root: here,
  logLevel: "error",
  server: { middlewareMode: true },
  appType: "custom",
  plugins: [
    {
      name: "c",
      transform(code, id) {
        if (!id.endsWith("/src/config.ts")) return null;
        return code.replace(
          /const meta = [^;]*;/,
          `const meta = { env: ${JSON.stringify({
            VITE_API_BASE_URL: API,
          })} };`
        );
      },
    },
  ],
});

const { SampleRegisterTab } = await vite.ssrLoadModule(
  path.resolve(
    here,
    "src/pages/ProjectWorkspace/LabData/tabs/SampleRegisterTab.tsx"
  )
);

const el = document.getElementById("root");
const root = createRoot(el);
const wait = (ms = 1600) =>
  act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
const click = (node) =>
  act(async () => {
    node.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  });
const out = [];
const check = (n, c) => out.push(`${c ? "PASS" : "FAIL"} ${n}`);

await act(async () => {
  root.render(React.createElement(SampleRegisterTab, { projectId: PROJECT }));
});
await wait();

check(
  "renders the Sample Register heading",
  el.textContent.includes("Sample Register")
);
check(
  "shows Soil and Rock views",
  [...el.querySelectorAll(".sampling-view-tab")]
    .map((b) => b.textContent)
    .join(",") === "Soil,Rock"
);
check(
  "location filter lists every borehole",
  [...el.querySelectorAll("select option")]
    .map((o) => o.textContent)
    .join(",") === ["All Locations", ...locaIds].join(",")
);

// Rock is the default view, as it was in Field Data.
check(
  "Rock is the default view",
  el.querySelectorAll(".sampling-view-tab")[1].className.includes("active")
);
check(
  "Rock view lists approved runs or explains where they come from",
  register.rock.length > 0
    ? el.querySelectorAll("tbody tr").length === register.rock.length
    : el.textContent.includes("No approved Rock data") &&
      el.textContent.includes("Field Data")
);

// Switch to Soil.
await click(el.querySelectorAll(".sampling-view-tab")[0]);
await wait();
check(
  "Soil tab lists approved SPT samples",
  el.querySelectorAll("tbody tr").length === register.soil.length
);
check(
  "Soil shows a Location column on All Locations",
  [...el.querySelectorAll("thead th")].map((t) => t.textContent).includes(
    "Location"
  )
);
check(
  "Soil columns match the old viewer",
  [...el.querySelectorAll("thead th")]
    .map((t) => t.textContent)
    .join("|") ===
    "Sample ID|Location|Depth (m)|Blows @15cm|Blows @30cm|Blows @45cm|SPT N-value|Created By"
);
check(
  "rows span more than one borehole",
  new Set(
    [...el.querySelectorAll("tbody tr")].map((r) => r.children[1].textContent)
  ).size > 1
);

// Narrow to one location.
const sel = el.querySelector("select");
await act(async () => {
  Object.getOwnPropertyDescriptor(
    dom.window.HTMLSelectElement.prototype,
    "value"
  ).set.call(sel, target);
  sel.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
});
await wait();

check(
  `filtering to ${target} refetches the register with loca_id`,
  seen.some((u) => u.includes(`sample-register?loca_id=${targetParam}`))
);

// The Location column is gone on a single location, so compare Sample IDs
// against the server's own answer rather than reading a column positionally.
const shown = new Set(
  [...el.querySelectorAll("tbody tr")].map((r) => r.children[0].textContent)
);
const want = new Set(expected.map((r) => r.sample_id));
check(
  `rows shown are exactly ${target}'s samples`,
  shown.size === want.size && [...shown].every((id) => want.has(id))
);
check(
  "Location column disappears on a single location",
  ![...el.querySelectorAll("thead th")]
    .map((t) => t.textContent)
    .includes("Location")
);
check(
  "filtering actually reduced the row count",
  want.size < register.soil.length
);

const bad = out.filter((l) => l.startsWith("FAIL")).length;
console.log(out.join("\n"));
console.log(`\n${out.length - bad}/${out.length} passed`);
console.log(
  "requests:",
  seen.filter((u) => u.includes("sample-register")).length
);
process.exit(bad ? 1 : 0);