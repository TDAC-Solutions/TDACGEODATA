/* Runtime smoke test: creating a project opens its workspace.

   Regression guard for the old behaviour where a successful create sent
   the user back to the portfolio ("/") instead of the project they just
   made. It renders the REAL App, fills the real form, submits it, and
   asserts the browser lands on /#/project/<number returned by the API>.
   The stubbed API answers with a different number than the previewed
   next-id, so the test also proves the redirect uses the server response
   (the only safe source) rather than the form field.

   Run: node run-smoke.mjs smoke-create-project-redirect.test.mjs */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost/#/projects/new",
  pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.HTMLElement = dom.window.HTMLElement;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.localStorage = dom.window.localStorage;

dom.window.localStorage.setItem("access_token", "test-token");
dom.window.localStorage.setItem("refresh_token", "test-refresh");

// The form previews this number...
const PREVIEWED_ID = "TDAC-2099-01-001";
// ...but the server allocates a different one (simulated race). The app
// must ignore the preview and follow the response.
const ALLOCATED_ID = "TDAC-2099-01-077";
const CREATED_NAME = "Smoke Test Viaduct";

let createRequestBody = null;

global.fetch = dom.window.fetch = async (url, opts = {}) => {
  const target = String(url);
  const json = (body) => ({
    ok: true,
    status: 200,
    json: async () => body,
    headers: { get: () => "application/json" },
  });

  if (target.includes("/api/auth/home")) {
    return json({ message: "ok", user: { id: 1, username: "test-admin", role: "admin" } });
  }

  if (target.includes("/api/portfolio/projects/next-id")) {
    return json({ project_id: PREVIEWED_ID });
  }

  if (target.includes("/api/portfolio/projects") && opts.method === "POST") {
    createRequestBody = JSON.parse(opts.body);
    return json({
      message: "Project created successfully",
      project: {
        project_number: ALLOCATED_ID,
        project_name: CREATED_NAME,
        country_region: "Kochi",
        client: "KMRL",
      },
    });
  }

  // The workspace mounts after the redirect; answer its reads with an
  // empty-but-valid shape so nothing throws on the way in.
  if (target.includes("/locas")) {
    return json({ project_id: ALLOCATED_ID, locas: [] });
  }
  if (/\/api\/portfolio\/projects\/[^/]+$/.test(target)) {
    return json({
      project_id: ALLOCATED_ID,
      project_name: CREATED_NAME,
      project_location: "Kochi",
      project_client: "KMRL",
      consultant_name: "Consultant LLP",
      contractor_name: "Contractor Pvt Ltd",
      project_type: "LAB_AND_REPORT",
    });
  }

  return json({ projects: [], total_projects: 0, active_projects: 0, completed_projects: 0 });
};

const { createRoot } = await import("react-dom/client");
const { act } = await import("react");
const React = await import("react");
const { default: App } = await import("./src/App.tsx");
const { AuthProvider } = await import("./src/auth/AuthContext.tsx");

const root = createRoot(document.getElementById("root"));
await act(async () => {
  root.render(React.createElement(AuthProvider, null, React.createElement(App)));
});
await act(async () => { await new Promise((r) => setTimeout(r, 50)); });

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);

// React ignores direct .value writes; go through the native setter and
// dispatch the event React actually listens to (input for text-ish
// controls, change for selects).
function setValue(name, value) {
  const el = document.querySelector(`[name="${name}"]`);
  if (!el) throw new Error(`field ${name} not found`);
  const proto =
    el.tagName === "TEXTAREA"
      ? dom.window.HTMLTextAreaElement.prototype
      : el.tagName === "SELECT"
        ? dom.window.HTMLSelectElement.prototype
        : dom.window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
  el.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  el.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
}

await act(async () => { await new Promise((r) => setTimeout(r, 30)); });

// 1. The page rendered and the previewed ID arrived from the API.
check("Add New Project page rendered",
  document.querySelector(".page-title")?.textContent === "Add New Project");
check("automatic ID preview filled",
  document.querySelector('input[name="project_id"]')?.value === PREVIEWED_ID);

// 2. Fill every field handleSubmit validates. Wrapped in act so React
//    flushes each state update before the submit is fired.
await act(async () => {
  setValue("project_name", CREATED_NAME);
  setValue("project_type", "LAB_AND_REPORT");
  setValue("project_location", "Kochi");
  setValue("project_client", "KMRL");
  setValue("road_reference", "NH-66");
  setValue("chainage_text", "CH 10+000 to CH 12+500");
  setValue("structure_reference", "Pier P12");
  setValue("selected_boreholes", "BH-01, BH-02");
  setValue("consultant_name", "Consultant LLP");
  setValue("contractor_name", "Contractor Pvt Ltd");
  setValue("report_type", "Factual");
  setValue("report_title", "GI Factual Report");
  setValue("report_volume_title", "Volume I");
  setValue("document_reference", "TDAC/REP/2026/01");
  setValue("revision", "R0");
  setValue("report_date", "2026-10-17");
  setValue("issue_status", "Draft");
  setValue("groundwater_basis", "Observed during drilling");
});

// 3. Submit the CREATE form specifically. The Topbar also owns a <form>
//    (the search box), so selecting by the project_name field avoids
//    submitting the wrong one.
const createForm = document
  .querySelector('[name="project_name"]')
  .closest("form");
await act(async () => {
  createForm.dispatchEvent(
    new dom.window.Event("submit", { bubbles: true, cancelable: true })
  );
});
await act(async () => { await new Promise((r) => setTimeout(r, 60)); });

// 4. The critical assertions. A missing POST would mean validation stopped
//    the submit, and the hash assertions below would fail with it.
check("the create form left the screen",
  !document.querySelector('[name="project_name"]'));
check("submitted AUTO so the server allocates",
  createRequestBody?.project_id === "AUTO");
check("metadata carries the selected project type",
  createRequestBody?.metadata?.project_type === "LAB_AND_REPORT");
check("redirected into the new project workspace",
  window.location.hash === `#/project/${ALLOCATED_ID}`);
check("redirect used the server-allocated number, not the preview",
  !window.location.hash.includes(PREVIEWED_ID));

console.log(results.join("\n"));
const fails = results.filter((r) => r.startsWith("FAIL")).length;
if (fails) {
  console.error(`\n${fails} FAIL(S)`);
  process.exitCode = 1;
} else {
  console.log(`\n${results.length}/${results.length} green`);
}
root.unmount();
