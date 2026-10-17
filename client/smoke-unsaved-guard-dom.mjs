/* DOM test for the unsaved-changes guard, against the REAL workspace.
 *
 * smoke-unsaved-changes.mjs covers the decision logic in isolation. This
 * covers the part that logic cannot: that the SPT grid actually reports
 * itself dirty through context, that the workspace tab bar consults it, and
 * that window.confirm really gates the tab change.
 *
 * The failure being guarded: gridRows is component state, the workspace
 * renders one tab at a time, so leaving the tab unmounts the grid and the
 * typed rows are gone with no prompt.
 */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost/#/project/TDAC-TEST-001",
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
if (!keyMatch) {
  console.log("AUTH STORAGE KEY NOT FOUND - test cannot proceed");
  process.exit(2);
}
dom.window.localStorage.setItem(keyMatch[1], "smoke-token");
dom.window.localStorage.setItem("refresh_token", "smoke-refresh");

const json = (body) => ({
  ok: true,
  status: 200,
  json: async () => body,
  headers: { get: () => "application/json" },
});

global.fetch = dom.window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/auth/home")) {
    return json({ message: "ok", user: { id: 1, username: "a", role: "admin" } });
  }
  // MUST be first: an audit URL ends in its mode (".../audit/borehole"),
  // so it collides with the /borehole branch below, and it contains "/locas"
  // as well. Anything later in this list answers it with the wrong shape.
  if (u.includes("/field-data/audit/")) return json({ entries: [] });

  if (u.includes("/spt")) return json({ records: [], pending: [] });
  if (u.includes("/rock")) return json({ records: [], pending: [] });
  if (u.includes("/borehole")) return json({ records: [] });
  if (u.includes("/groundwater")) return json({ records: [] });
  // The Field Data Overview module mounts the borelog preview by default, and
  // it reads rows/columns/layers straight off the response. An empty {} there
  // is a TypeError, not an error state.
  if (u.includes("borelog")) {
    return json({
      project_id: "TDAC-TEST-001",
      loca_id: "BH-1",
      header: {},
      columns: [],
      rows: [],
      layers: [],
      spt: [],
      summary: { layer_count: 0, spt_count: 0, rock_count: 0 },
    });
  }
  if (u.includes("/locas")) {
    return json({
      locas: [{ loca_id: "BH-1", loca_name: "BH-1", loca_type: "BH", project_id: "TDAC-TEST-001" }],
    });
  }
  if (u.includes("/lab/tests")) return json({ tests: [] });
  if (u.includes("/method")) return json({ methods: [] });
  if (u.includes("/samples")) return json({ samples: [] });
  if (u.includes("/api/portfolio/projects/")) {
    return json({
      project_id: "TDAC-TEST-001",
      project_name: "Smoke",
      project_location: "Site",
      project_client: "Client",
    });
  }
  // Fallback: an object carrying every list key the Field Data panels read
  // off a response. Without it a panel that does `result.entries.length` on
  // an empty {} is a TypeError before the test reaches what it is testing.
  // This suite is about the unsaved-changes guard, not API shape fidelity.
  return json({
    entries: [],
    tests: [],
    samples: [],
    records: [],
    pending: [],
    rows: [],
    columns: [],
    layers: [],
    spt: [],
    methods: [],
    projects: [],
    locas: [],
    items: [],
    data: [],
    summary: { layer_count: 0, spt_count: 0, rock_count: 0 },
  });
};

const React = await import("react");
const { act } = React;
const { createRoot } = await import("react-dom/client");
const { AuthProvider } = await import("./src/auth/AuthContext.tsx");
// Render the real App, not the page directly. ProjectWorkspacePage reads
// projectId from useParams(), which is only populated inside a matching
// <Route>, so rendering the page bare yields projectId === undefined and
// every fetch 404s. App owns its own HashRouter, which picks the route up
// from the jsdom URL set at the top of this file.
const { default: App } = await import("./src/App.tsx");

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 60)); });
const click = (el, what) => act(async () => {
  if (!el) throw new Error(`click target not found: ${what ?? "element"}`);
  el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
});
const tab = (label) =>
  [...document.querySelectorAll("nav.tabs button")].find((b) => b.textContent.trim() === label);

const root = createRoot(document.getElementById("root"));
await act(async () => {
  root.render(
    React.createElement(React.StrictMode, null,
      React.createElement(AuthProvider, null,
        React.createElement(App)))
  );
});
await settle();

check("workspace rendered", !!document.querySelector(".projectbar"));

// Navigate into Field Data, then the SPT module.
await click(tab("Field Data"), "tab Field Data");
await settle();
check("Field Data open", !!document.querySelector(".field-layout"));

const sptTab = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("SPT"));
await click(sptTab);
await settle();

// Open the entry grid.
const opener = [...document.querySelectorAll("button")].find((b) => /Enter SPT Data/.test(b.textContent));
check("SPT entry grid opener found", !!opener);
await click(opener);
await settle();

const cell = document.querySelector('[data-spt-cell="0:spt_depth"]');
check("SPT depth cell rendered", !!cell);

// --- control: a pristine grid must never nag --------------------------
let confirms = [];
let answer = false;
dom.window.confirm = (msg) => { confirms.push(msg); return answer; };

confirms = [];
await click(tab("Lab Data"), "tab Lab Data");
await settle();
check("pristine grid does not prompt", confirms.length === 0);
check("navigated away from a pristine grid", !document.querySelector(".field-layout"));

// Go back and dirty the grid.
await click(tab("Field Data"), "tab Field Data");
await settle();
const sptTab2 = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("SPT"));
await click(sptTab2);
await settle();
const opener2 = [...document.querySelectorAll("button")].find((b) => /Enter SPT Data/.test(b.textContent));
await click(opener2);
await settle();

const cell2 = document.querySelector('[data-spt-cell="0:spt_depth"]');
check("grid reopened for the dirty test", !!cell2);

if (cell2) {
  // Type a depth the way a user does: through React's onChange.
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(cell2, "1.5");
    cell2.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  await settle();

  check("typed value reached the grid", cell2.value === "1.5");

  // --- declining must keep the user and the data ----------------------
  confirms = [];
  answer = false;
  await click(tab("Lab Data"), "tab Lab Data");
  await settle();

  check("dirty grid prompted before discarding", confirms.length === 1);
  check("prompt names the SPT grid", confirms[0]?.includes("SPT entry grid") === true);
  check("prompt warns rows are not saved", confirms[0]?.includes("not been submitted") === true);
  check("declining kept us on Field Data", !!document.querySelector(".field-layout"));
  check("declining preserved the typed value",
    document.querySelector('[data-spt-cell="0:spt_depth"]')?.value === "1.5");

  // --- accepting must proceed ----------------------------------------
  confirms = [];
  answer = true;
  await click(tab("Lab Data"), "tab Lab Data");
  await settle();
  check("accepting prompted once", confirms.length === 1);
  check("accepting left Field Data", !document.querySelector(".field-layout"));

  // --- and returning must not leave a phantom warning ---------------
  // A grid that unmounts must withdraw its flag, or the user is nagged
  // forever about rows they can no longer even see.
  await click(tab("Field Data"), "tab Field Data");
  await settle();
  confirms = [];
  answer = false;
  await click(tab("Lab Data"), "tab Lab Data");
  await settle();
  check("no phantom warning after the grid unmounted", confirms.length === 0);
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);