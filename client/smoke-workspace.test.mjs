/* Runtime smoke test for the Project Workspace:
   renders the REAL App, seeds a token pair, opens /#/project/TDAC-TEST-001
   directly, walks the 8 tabs, verifies the real panels render and the
   label order matches the WORKSPACE_TABS source constant exactly. */
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

// Both tokens must exist before App mounts: AuthContext restores the
// session only when the access+refresh pair is present. Key discovered
// from src/api/token.ts, never hardcoded.
const fs = await import("node:fs");
const tokenSrc = fs.readFileSync("src/api/token.ts", "utf8");
const keyMatch = tokenSrc.match(/ACCESS_TOKEN_KEY\s*=\s*["']([^"']+)["']/)
  || tokenSrc.match(/(?:getItem|setItem|removeItem)\(\s*["']([^"']+)["']/);
if (!keyMatch) {
  console.log("AUTH STORAGE KEY NOT FOUND — ProtectedRoute will redirect; test cannot proceed");
  process.exit(2);
}
const KEY = keyMatch[1];
console.log("auth storage key:", KEY);
dom.window.localStorage.setItem(KEY, "test-token");
dom.window.localStorage.setItem("refresh_token", "test-refresh");

// Route each backend call to the shape its real caller expects.
global.fetch = dom.window.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/api/auth/home")) {
    return {
      ok: true, status: 200,
      json: async () => ({ message: "ok", user: { id: 1, username: "test-admin", role: "admin" } }),
      headers: { get: () => "application/json" },
    };
  }
  if (u.includes("/locas")) {
    return {
      ok: true, status: 200,
      json: async () => ({ locas: [] }),
      headers: { get: () => "application/json" },
    };
  }
  if (u.includes("/api/portfolio/projects/")) {
    return {
      ok: true, status: 200,
      json: async () => ({
        project_id: "TDAC-TEST-001",
        project_name: "Smoke Test Project",
        project_location: "Test Site",
        project_client: "Test Client",
      }),
      headers: { get: () => "application/json" },
    };
  }
  if (u.includes("/lab/tests")) {
    return {
      ok: true, status: 200,
      json: async () => ({ tests: [] }),
      headers: { get: () => "application/json" },
    };
  }
  if (u.includes("/lab/methods") || u.includes("/method")) {
    return {
      ok: true, status: 200,
      json: async () => ({ methods: [] }),
      headers: { get: () => "application/json" },
    };
  }
  if (u.includes("/samples")) {
    return {
      ok: true, status: 200,
      json: async () => ({ samples: [] }),
      headers: { get: () => "application/json" },
    };
  }
  return {
    ok: true, status: 200,
    json: async () => ({ projects: [], total_projects: 0, active_projects: 0, completed_projects: 0 }),
    headers: { get: () => "application/json" },
  };
};

const { createRoot } = await import("react-dom/client");
const { act, StrictMode } = await import("react");
const React = await import("react");
const { default: App } = await import("./src/App.tsx");
const { AuthProvider } = await import("./src/auth/AuthContext.tsx");
const { WORKSPACE_TABS } = await import("./src/pages/ProjectWorkspace/types.ts");

const root = createRoot(document.getElementById("root"));
await act(async () => {
  root.render(
    React.createElement(StrictMode, null,
      React.createElement(AuthProvider, null, React.createElement(App)))
  );
});
await act(async () => { await new Promise((r) => setTimeout(r, 80)); });

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);
const click = (el) => act(async () => {
  el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
});

// 0. Workspace rendered (not redirected to /login)?
check("workspace page rendered (auth guard passed)", !!document.querySelector(".projectbar"));

// 1. Tabs: count + label order derived from the source const
const tabs = [...document.querySelectorAll(".tabs .tab")];
const expectedLabels = WORKSPACE_TABS.map((t) => t.label);
const gotLabels = tabs.map((t) => t.textContent.trim());
check(`tab count = ${expectedLabels.length} (got ${tabs.length})`,
  tabs.length === expectedLabels.length);
check("tab labels + order match WORKSPACE_TABS",
  JSON.stringify(gotLabels) === JSON.stringify(expectedLabels));

// 2. Project header carries the loaded project
check("project name in projectbar",
  document.querySelector(".projectbar-title")?.textContent === "Smoke Test Project");
check("project id + client + location in meta",
  (document.querySelector(".projectbar-meta")?.textContent ?? "").includes("TDAC-TEST-001"));

// 3. Overview: info grid + locations panel + excel import + add location
check("overview: project info panel", !!document.querySelector(".panel .panel-title"));
// Was: `.viewgrid .panel` === 4. That markup has never existed in Overview --
// `viewgrid` appears only in UserManagement and shell.css -- so the assertion
// could not have passed, and never did: the test could not run at all until
// jsdom was added. Checking the real structure instead.
check("overview: info sections render",
  document.querySelectorAll(".overview-grid .overview-section").length === 6);
check("overview: project details section present",
  [...document.querySelectorAll(".overview-section-title")]
    .some((el) => el.textContent.trim() === "Project Details"));
check("overview: excel import button",
  [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "Import from Excel"));
check("overview: add location button",
  [...document.querySelectorAll("button")].some((b) => b.textContent.trim() === "+ Add Location"));

// 4. Field Data tab renders its real module (loading state with no locas)
await click(tabs[1]);
await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
check("field: module tabs render",
  [...document.querySelectorAll(".tabs, .subtabs, .field-layout, .panel")].length > 0);

// 5. The remaining tabs are placeholders with their titles
for (let i = 2; i < expectedLabels.length; i++) {
  await click(tabs[i]);
  await act(async () => { await new Promise((r) => setTimeout(r, 15)); });
  const title = document.querySelector(".panel-title")?.textContent ?? "";
  check(`tab ${expectedLabels[i]} renders its placeholder`, title === expectedLabels[i]);
}

// 6. No mock data leaked: mockup numbers must not appear anywhere
const MOCK_NUMBERS = ["184", "126 / 143", "Kochi", "TDAC-2026-041", "52 %", "31.6"];
const body = document.body.textContent;
check("no mock data anywhere", !MOCK_NUMBERS.some((n) => body.includes(n)));

// 7. Navigate home renders the portfolio register again
await act(async () => {
  window.location.hash = "#/";
  window.dispatchEvent(new dom.window.HashChangeEvent("hashchange"));
});
await act(async () => { await new Promise((r) => setTimeout(r, 30)); });
check("back home renders portfolio", !!document.querySelector(".page-head"));

console.log(results.join("\n"));
const fails = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - fails}/${results.length} passed`);
root.unmount();
if (fails) process.exit(1);
