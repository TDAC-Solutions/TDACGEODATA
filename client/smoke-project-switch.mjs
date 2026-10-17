/* Project-switch behaviour against the real App.
 *
 * Two things are asserted here:
 *   1. Switching projects actually resets workspace state. LabData carries
 *      key={projectId} because React reuses a component when only a route
 *      param changes -- without the key, project B inherits project A's open
 *      sub-tab, selected test and filters.
 *   2. Whether unsaved grid rows survive or are silently dropped.
 *
 * (2) is an open question, not an assumption: the tab guard covers in-app
 * tab clicks, but a project change is a route change and may bypass it. The
 * test records what actually happens rather than what should happen.
 */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost/#/project/PROJ-A",
  pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.HTMLElement = dom.window.HTMLElement;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.localStorage = dom.window.localStorage;

const fs = await import("node:fs");
const tokenSrc = fs.readFileSync("src/api/token.ts", "utf8");
const keyMatch = tokenSrc.match(/ACCESS_TOKEN_KEY\s*=\s*["']([^"']+)["']/)
  || tokenSrc.match(/(?:getItem|setItem|removeItem)\(\s*["']([^"']+)["']/);
dom.window.localStorage.setItem(keyMatch[1], "smoke-token");
dom.window.localStorage.setItem("refresh_token", "smoke-refresh");

const json = (body) => ({
  ok: true, status: 200, json: async () => body,
  headers: { get: () => "application/json" },
});

global.fetch = dom.window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/auth/home")) {
    return json({ message: "ok", user: { id: 1, username: "a", role: "admin" } });
  }
  if (u.includes("/field-data/audit/")) return json({ entries: [] });
  if (u.includes("/spt")) return json({ records: [], pending: [] });
  if (u.includes("/rock")) return json({ records: [], pending: [] });
  if (u.includes("/borehole")) return json({ records: [] });
  if (u.includes("/groundwater")) return json({ records: [] });
  if (u.includes("borelog")) {
    return json({
      project_id: "PROJ-A", loca_id: "BH-1", header: {}, columns: [], rows: [],
      layers: [], spt: [], summary: { layer_count: 0, spt_count: 0, rock_count: 0 },
    });
  }
  if (u.includes("/locas")) {
    return json({ locas: [{ loca_id: "BH-1", loca_name: "BH-1", loca_type: "BH" }] });
  }
  if (u.includes("/lab/tests")) return json({ tests: [] });
  if (u.includes("/method")) return json({ methods: [] });
  if (u.includes("/samples")) return json({ samples: [] });
  if (u.includes("/metadata")) return json({ report_type: "BS", revision: "0" });
  if (u.includes("/api/portfolio/projects/")) {
    const id = u.split("/projects/")[1]?.split("/")[0];
    return json({ project_id: id, project_name: `Name ${id}`, project_location: "Site", project_client: "Client" });
  }
  return json({
    entries: [], tests: [], samples: [], records: [], pending: [], rows: [],
    columns: [], layers: [], spt: [], methods: [], projects: [], locas: [],
    items: [], data: [], summary: { layer_count: 0, spt_count: 0, rock_count: 0 },
  });
};

const React = await import("react");
const { act } = React;
const { createRoot } = await import("react-dom/client");
const { default: App } = await import("./src/App.tsx");
const { AuthProvider } = await import("./src/auth/AuthContext.tsx");

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 70)); });
const click = (el, what) => act(async () => {
  if (!el) throw new Error(`click target not found: ${what}`);
  el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
});
const tab = (label) =>
  [...document.querySelectorAll("nav.tabs button")].find((b) => b.textContent.trim() === label);

const root = createRoot(document.getElementById("root"));
await act(async () => {
  root.render(
    React.createElement(React.StrictMode, null,
      React.createElement(AuthProvider, null, React.createElement(App)))
  );
});
await settle();

check("project A loaded", document.querySelector(".projectbar-title")?.textContent.includes("PROJ-A"));
check("starts on the Overview tab", tab("Overview")?.getAttribute("aria-selected") === "true");

// Dirty a grid, then change project.
await click(tab("Field Data"), "tab Field Data");
await settle();
const sptTab = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("SPT"));
await click(sptTab, "SPT module");
await settle();
const opener = [...document.querySelectorAll("button")].find((b) => /Enter SPT Data/.test(b.textContent));
await click(opener, "SPT entry opener");
await settle();

const cell = document.querySelector('[data-spt-cell="0:spt_depth"]');
check("SPT grid open with a cell", !!cell);
if (cell) {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(cell, "1.5");
    cell.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  await settle();
  check("value typed into the grid", cell.value === "1.5");
}

let confirms = [];
dom.window.confirm = (msg) => { confirms.push(msg); return true; };

// Navigate to another project the way the browser does: change the hash.
confirms = [];
await act(async () => {
  dom.window.location.hash = "#/project/PROJ-B";
  dom.window.dispatchEvent(new dom.window.HashChangeEvent("hashchange"));
});
await settle();

check("project B loaded", document.querySelector(".projectbar-title")?.textContent.includes("PROJ-B"));
check("switching project returned to the Overview tab",
  tab("Overview")?.getAttribute("aria-selected") === "true");
check("the dirty grid was unmounted",
  document.querySelector('[data-spt-cell="0:spt_depth"]') === null);
check("no stale project A data left in the title",
  !document.querySelector(".projectbar-title")?.textContent.includes("PROJ-A"));

// Report, do not assert, what happens to unsaved rows on a project change.
results.push(
  confirms.length === 0
    ? "NOTE unsaved rows are discarded on a project change with no prompt"
    : `PASS project change prompted before discarding (${confirms.length})`
);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);