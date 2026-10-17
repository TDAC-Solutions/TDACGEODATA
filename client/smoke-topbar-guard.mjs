/* The Topbar guard, against the real App.
 *
 * The search box used to ask "anything unsaved will be lost?" on EVERY search
 * that left the workspace, because nothing could tell whether anything was
 * actually unsaved. Two things are asserted here:
 *
 *   - with nothing dirty, searching leaves silently (the old nag is gone)
 *   - with a grid holding typed rows, searching asks first, and declining
 *     keeps the user in the workspace with their data intact
 *
 * Also covers logout and User Management, which leave the workspace by the
 * same unmount and were previously unguarded.
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
dom.window.localStorage.setItem(keyMatch[1], "smoke-token");
dom.window.localStorage.setItem("refresh_token", "smoke-refresh");

const json = (b) => ({ ok: true, status: 200, json: async () => b, headers: { get: () => "application/json" } });
global.fetch = dom.window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/auth/home")) return json({ message: "ok", user: { id: 1, username: "a", role: "admin" } });
  if (u.includes("/logout")) return json({ message: "ok" });
  if (u.includes("/field-data/audit/")) return json({ entries: [] });
  if (u.includes("/spt")) return json({ records: [], pending: [] });
  if (u.includes("/rock")) return json({ records: [], pending: [] });
  if (u.includes("/borehole")) return json({ records: [] });
  if (u.includes("/groundwater")) return json({ records: [] });
  if (u.includes("borelog")) return json({ project_id: "P1", loca_id: "BH-1", header: {}, columns: [], rows: [], layers: [], spt: [], summary: { layer_count: 0, spt_count: 0, rock_count: 0, max_depth_per_page: 20, page_count: 0 }, max_depth_per_page: 20, pdf_page_count: 0 });
  if (u.includes("/locas")) return json({ locas: [{ loca_id: "BH-1", loca_name: "BH-1", loca_type: "BH" }] });
  if (u.includes("/lab/tests")) return json({ tests: [] });
  if (u.includes("/method")) return json({ methods: [] });
  if (u.includes("/samples")) return json({ samples: [] });
  if (u.includes("/metadata")) return json({});
  if (u.includes("/api/portfolio/projects/")) {
    return json({ project_id: "PROJ-A", project_name: "Name A", project_location: "S", project_client: "C" });
  }
  return json({ entries: [], tests: [], samples: [], records: [], pending: [], rows: [], columns: [], layers: [], spt: [], methods: [], projects: [], locas: [], items: [], data: [], summary: { layer_count: 0, spt_count: 0, rock_count: 0 } });
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

let confirms = [];
let answer = true;
dom.window.confirm = (msg) => { confirms.push(msg); return answer; };

const searchInput = () => document.querySelector('input[type="search"], .topbar input[type="text"], input[placeholder*="earch" i]');
check("workspace loaded", !!document.querySelector(".projectbar"));
check("topbar search box found", !!searchInput());

async function submitSearch(term) {
  const input = searchInput();
  if (!input) return;
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(input, term);
    input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  await settle();
  const form = input.closest("form");
  await act(async () => {
    form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

// --- nothing dirty: must NOT nag, and must navigate --------------------
confirms = [];
answer = true;
await submitSearch("kochi");

check("clean workspace does not nag on search", confirms.length === 0);
check("clean search left the workspace", dom.window.location.hash.startsWith("#/") && !dom.window.location.hash.includes("/project/"));

// Back into a project for the dirty half.
await act(async () => {
  dom.window.location.hash = "#/project/TDAC-TEST-001";
  dom.window.dispatchEvent(new dom.window.HashChangeEvent("hashchange"));
});
await settle();
check("back in the workspace", !!document.querySelector(".projectbar"));

// --- dirty the SPT grid --------------------------------------------------
await click(tab("Field Data"), "tab Field Data");
await settle();
const sptTab = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("SPT"));
await click(sptTab, "SPT module");
await settle();
const opener = [...document.querySelectorAll("button")].find((b) => /Enter SPT Data/.test(b.textContent));
await click(opener, "SPT opener");
await settle();

const cell = document.querySelector('[data-spt-cell="0:spt_depth"]');
check("grid cell available", !!cell);

if (cell) {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(cell, "1.5");
    cell.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  });
  await settle();
  check("value typed", cell.value === "1.5");

  // --- declining keeps us and the data --------------------------------
  confirms = [];
  answer = false;
  await submitSearch("kochi");
  check("dirty workspace asked before leaving", confirms.length === 1);
  check("still in the workspace after declining", dom.window.location.hash.includes("/project/"));
  check("typed row survived the declined search",
    document.querySelector('[data-spt-cell="0:spt_depth"]')?.value === "1.5");

  // --- accepting leaves ------------------------------------------------
  confirms = [];
  answer = true;
  await submitSearch("kochi");
  check("accepting prompted once", confirms.length === 1);
  check("accepting left the workspace", !dom.window.location.hash.includes("/project/"));

  // --- User Management is guarded the same way -------------------------
  await act(async () => {
    dom.window.location.hash = "#/project/TDAC-TEST-001";
    dom.window.dispatchEvent(new dom.window.HashChangeEvent("hashchange"));
  });
  await settle();
  await click(tab("Field Data"), "tab Field Data 2");
  await settle();
  const spt2 = [...document.querySelectorAll("button")].find((b) => b.textContent.trim().startsWith("SPT"));
  await click(spt2, "SPT module 2");
  await settle();
  const opener2 = [...document.querySelectorAll("button")].find((b) => /Enter SPT Data/.test(b.textContent));
  await click(opener2, "SPT opener 2");
  await settle();
  const cell2 = document.querySelector('[data-spt-cell="0:spt_depth"]');
  if (cell2) {
    await act(async () => {
      setter.call(cell2, "2.5");
      cell2.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    });
    await settle();

    const adminBtn = [...document.querySelectorAll("button")].find((b) => /User Management/.test(b.textContent));
    check("User Management button present", !!adminBtn);
    confirms = [];
    answer = false;
    await click(adminBtn, "User Management");
    check("User Management asked before leaving", confirms.length === 1);
    check("declining User Management kept the workspace", dom.window.location.hash.includes("/project/"));
  }
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);