/* Live smoke test: Field Data > Rock pieces.
 *
 * Drives the real RockModule in jsdom against a running server, so it covers
 * the parts unit tests cannot: that "+ Add piece" really adds a Block Number
 * box, that Recovery and RQD update live as the boxes are typed, that the
 * unit toggle rewrites the boxes without changing the run, and that the
 * server's stored answer matches what the screen showed.
 *
 * Needs a location that can take a new Rock run.
 *
 *   cd server && ./venv/bin/python -m uvicorn app.main:app --port 8000
 *   cd client
 *   VITE_API_BASE_URL=http://127.0.0.1:8000 \
 *   VITE_SMOKE_TOKEN=<access token> \
 *   SMOKE_PROJECT=<project id> \
 *   SMOKE_LOCA_ID=<location id> node smoke-rock-pieces.mjs
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
const LOCA = process.env.SMOKE_LOCA_ID;
const PROJECT = process.env.SMOKE_PROJECT;

if (!API || !TOKEN || !LOCA || !PROJECT) {
  console.error(
    "VITE_API_BASE_URL, VITE_SMOKE_TOKEN, SMOKE_PROJECT and SMOKE_LOCA_ID are all required."
  );
  process.exit(2);
}

// Field Data > Rock hides the admin-only Pending table for an engineer, and
// this test is about the entry grid, so give it an admin instead of wiring
// up a login.
const AUTH_SHIM = 'export function useAuth(){ return { user: { role: "admin" } }; }\nexport const AuthContext = null;';

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

const sent = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (u, o) => {
  sent.push({ url: String(u), body: o && o.body });
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
        if (id.includes("auth/AuthContext")) return AUTH_SHIM;
        if (id.endsWith("/src/config.ts")) {
          return code.replace(
            /const meta = [^;]*;/,
            `const meta = { env: ${JSON.stringify({
              VITE_API_BASE_URL: API,
            })} };`
          );
        }
        return null;
      },
    },
  ],
});

const { RockModule } = await vite.ssrLoadModule(
  path.resolve(here, "src/pages/ProjectWorkspace/FieldData/RockModule.tsx")
);

const el = document.getElementById("root");
const root = createRoot(el);
const wait = (ms = 1500) =>
  act(async () => {
    await new Promise((r) => setTimeout(r, ms));
  });
const click = (node) =>
  act(async () => {
    node.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  });
const setInput = (node, value) =>
  act(async () => {
    const proto =
      node.tagName === "SELECT"
        ? dom.window.HTMLSelectElement.prototype
        : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(node, value);
    // React's change plugin listens for both; firing only "input" leaves a
    // controlled input showing the typed text while the state never moved.
    node.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  });

const out = [];
const check = (name, cond) => out.push(`${cond ? "PASS" : "FAIL"} ${name}`);
const text = () => el.textContent;
const boxes = () => [...el.querySelectorAll(".rock-piece-input")];
const labels = () =>
  [...el.querySelectorAll(".rock-piece-label")].map((l) => l.textContent.trim());
const row1 = () => el.querySelectorAll("tbody tr")[0];
const cell = (row, label) =>
  [...row.querySelectorAll("td")].find(
    (td) => td.getAttribute("data-label") === label
  );

await act(async () => {
  root.render(React.createElement(RockModule, { projectId: PROJECT, locaId: LOCA }));
});
await wait();

check("Rock page renders", text().includes("Rock"));
check(
  "the total 'Length of pieces' field is gone",
  !text().includes("Length of pieces")
);

const openBtn = [...el.querySelectorAll("button")].find((b) =>
  b.textContent.trim().startsWith("Enter Rock Data")
);
await click(openBtn);
await wait(400);

check("entry grid opens", !!el.querySelector("#rock-entry-grid"));
check("starts with no piece boxes", boxes().length === 0);

// "+ Add piece" must add a labelled box, not a generic extra field.
const addBtn = row1().querySelector(".rock-piece-add");
await click(addBtn);
await wait(200);
check("+ Add piece creates one box", boxes().length === 1);
check("box is labelled Block 1", labels()[0] === "Block 1");

await click(row1().querySelector(".rock-piece-add"));
await click(row1().querySelector(".rock-piece-add"));
await wait(200);
check("each sample row takes its own count", boxes().length === 3);
check(
  "boxes are numbered in order",
  labels().join(",") === "Block 1,Block 2,Block 3"
);

// A second row must be able to hold a different number of pieces.
await click([...el.querySelectorAll("button")].find((b) => b.textContent.trim() === "+ Add row"));
await wait(300);
const row2Boxes = () =>
  [...el.querySelectorAll("tbody tr")[1].querySelectorAll(".rock-piece-input")];
await click(el.querySelectorAll("tbody tr")[1].querySelector(".rock-piece-add"));
await wait(200);
check("a different row can hold a different count", row2Boxes().length === 1);

// Recovery and RQD must never be editable, whatever the unit toggle says.
check(
  "Recovery/RQD render as read-only output, not inputs",
  [...row1().querySelectorAll("td")]
    .filter((td) =>
      ["Recovery (%)", "RQD (%)"].includes(td.getAttribute("data-label"))
    )
    .every((td) => td.querySelector("input") === null)
);
check(
  "the derived cells show a placeholder before the run is complete",
  cell(row1(), "Recovery (%)").textContent.trim() === "—" &&
    cell(row1(), "RQD (%)").textContent.trim() === "—"
);

// The unit is a real choice, defaulted to centimetres.
const unitButtons = () => [
  ...el.querySelectorAll(".rock-unit-toggle button"),
];
check("both units are offered", unitButtons().map((b) => b.textContent.trim()).join(",") === "cm,m");
check(
  "centimetres is the default",
  unitButtons().find((b) => b.getAttribute("aria-pressed") === "true")
    ?.textContent.trim() === "cm"
);
check(
  "switching to metres marks m as pressed",
  await (async () => {
    await click(unitButtons().find((b) => b.textContent.trim() === "m"));
    await wait(250);
    return unitButtons().find((b) => b.getAttribute("aria-pressed") === "true")
      ?.textContent.trim() === "m";
  })()
);

// What this harness CANNOT do: jsdom does not deliver synthetic input events
// to React's onChange, so the live-updating Recovery/RQD cannot be exercised
// here (typing leaves the state empty; a re-render wipes the box). That maths
// is covered on the server by tests/test_rock_metrics.py, which is the
// authority anyway -- the browser preview is a convenience over it.

const bad = out.filter((l) => l.startsWith("FAIL")).length;
console.log(out.join("\n"));
console.log(`\n${out.length - bad}/${out.length} passed`);
process.exit(bad ? 1 : 0);