/* Renders the REAL QrCodeModal to verify the Sample Register handoff.
 *
 * Two behaviours under test, both added when the register stopped opening the
 * modal on its own terms:
 *   - initialScope makes the modal open on the view the register is showing,
 *     instead of always defaulting to "All samples" and quietly widening the
 *     set of samples the user is about to print labels for.
 *   - initialLocaId carries the register's location filter across.
 *
 * No backend: fetch is stubbed. The assertions are about the rendered radio
 * state, which is the whole contract of those props.
 */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost/",
  pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", { value: dom.window.navigator, configurable: true });
global.HTMLElement = dom.window.HTMLElement;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.localStorage = dom.window.localStorage;

// apiClient refuses to issue a request without a session token, so seed one.
// Key read from src/api/token.ts rather than hardcoded, for the same reason
// the workspace smoke does it.
const fs = await import("node:fs");
const tokenSrc = fs.readFileSync("src/api/token.ts", "utf8");
const keyMatch = tokenSrc.match(/ACCESS_TOKEN_KEY\s*=\s*["']([^"']+)["']/)
  || tokenSrc.match(/(?:getItem|setItem|removeItem)\(\s*["']([^"']+)["']/);
if (!keyMatch) {
  console.log("AUTH STORAGE KEY NOT FOUND - test cannot proceed");
  process.exit(2);
}
dom.window.localStorage.setItem(keyMatch[1], "smoke-token");

const requested = [];
global.fetch = dom.window.fetch = async (url) => {
  requested.push(String(url));
  return {
    ok: true,
    status: 200,
    json: async () => ({ samples: [] }),
    headers: { get: () => "application/json" },
  };
};

const React = await import("react");
const { act } = React;
const { createRoot } = await import("react-dom/client");
const { QrCodeModal } = await import(
  "./src/pages/ProjectWorkspace/LabData/tabs/QrCodeModal.tsx"
);

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);

async function renderModal(props) {
  requested.length = 0;
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);

  await act(async () => {
    root.render(
      React.createElement(QrCodeModal, {
        projectId: "TDAC-TEST-001",
        locas: [
          { loca_id: "BH-1", loca_name: "BH-1" },
          { loca_id: "BH-2", loca_name: "BH-2" },
        ],
        onClose: () => {},
        ...props,
      })
    );
  });
  await act(async () => { await new Promise((r) => setTimeout(r, 40)); });

  const radios = [...host.querySelectorAll('input[type="radio"]')];
  const selected = radios.find((r) => r.checked);
  const locationValue = host.querySelector("select")?.value;

  return { host, radios, selected, locationValue, root };
}

// --- default: still "All samples" ---------------------------------------
{
  const { selected, locationValue } = await renderModal({});
  check("modal renders its scope radios", !!selected);
  check("default scope is All samples", selected?.value === "all");
  check("default location is ALL", locationValue === "ALL");
}

// --- initialScope from the register's open view -------------------------
{
  const { selected } = await renderModal({ initialScope: "rock" });
  check("initialScope=rock opens on Rock only", selected?.value === "rock");
}

{
  const { selected } = await renderModal({ initialScope: "soil" });
  check("initialScope=soil opens on Soil only", selected?.value === "soil");
}

// --- initialLocaId carried across ---------------------------------------
{
  const { locationValue } = await renderModal({ initialLocaId: "BH-2" });
  check("initialLocaId preselects that borehole", locationValue === "BH-2");
}

// --- the request the modal actually makes must match the scope -----------
{
  await renderModal({ initialScope: "rock", initialLocaId: "BH-1" });
  const qrCall = requested.find((u) => u.includes("qr"));
  check("QR request is scoped to rock", !!qrCall && /rock/i.test(qrCall));
  check("QR request carries the borehole", !!qrCall && qrCall.includes("BH-1"));
}

// --- an error must NOT also claim there are no samples -------------------
// Regression: a failed request leaves `samples` empty, and the modal used to
// render the error AND "No approved samples match this filter" together.
// The second line is the opposite of the truth and sends people off to
// approve samples that already exist.
{
  global.fetch = dom.window.fetch = async () => ({
    ok: false,
    status: 404,
    json: async () => ({ detail: "Not Found" }),
    headers: { get: () => "application/json" },
  });

  const { host } = await renderModal({});
  const text = host.textContent ?? "";

  check("error is shown", text.includes("Not Found"));
  check(
    "error state does not also claim there are no approved samples",
    !text.includes("No approved samples match this filter")
  );
  check(
    "error explains the likely cause",
    /backend is running older code/i.test(text)
  );

  // And a genuinely empty result still says so.
  global.fetch = dom.window.fetch = async (url) => {
    requested.push(String(url));
    return {
      ok: true, status: 200,
      json: async () => ({ samples: [] }),
      headers: { get: () => "application/json" },
    };
  };
  const empty = await renderModal({});
  const emptyText = empty.host.textContent ?? "";
  check(
    "a genuinely empty result still reports no approved samples",
    emptyText.includes("No approved samples match this filter")
  );
  check(
    "a genuinely empty result shows no error",
    !emptyText.includes("running older code")
  );
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);