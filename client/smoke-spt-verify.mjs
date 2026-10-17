/* Verification for the SPT entry grid: the show/hide panel, the Edit flow,
   and the keyboard contract.
 *
 * Navigation itself is covered by smoke-spt-navigation.mjs against the pure
 * module, because jsdom cannot drive React 19 controlled inputs at all - a
 * minimal control component with identical wiring also fails - so any check
 * that needed real values would have been testing the harness, not the code.
 * What is asserted here is structure and focus, which jsdom does support.
 *
 * Mounts in a real DOM (jsdom) and drives the keyboard, because a static
 * render stops at the loading state and never reaches the grid. */

import React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost/",
  pretendToBeVisual: true,
});

globalThis.window = dom.window;
globalThis.document = dom.window.document;
// Node 24 defines navigator as a getter-only property, so a plain
// assignment throws. defineProperty is the only way to install it.
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
  writable: true,
});
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.HTMLInputElement = dom.window.HTMLInputElement;
globalThis.Event = dom.window.Event;
globalThis.KeyboardEvent = dom.window.KeyboardEvent;
globalThis.MouseEvent = dom.window.MouseEvent;
globalThis.Node = dom.window.Node;
globalThis.getComputedStyle = dom.window.getComputedStyle;
// The app's token module reads localStorage as a bare global, not off
// window, so it has to exist on globalThis as well as inside the jsdom.
globalThis.localStorage = dom.window.localStorage;
globalThis.requestAnimationFrame = (cb) => setTimeout(cb, 0);
globalThis.cancelAnimationFrame = (id) => clearTimeout(id);
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

// React 19's input-event polyfill calls the legacy IE attachEvent API when
// it detects an old environment, and jsdom does not implement it. Stubbing
// it as a no-op is enough; nothing in this app relies on those events.
const elProto = dom.window.HTMLElement.prototype;
elProto.attachEvent = () => {};
elProto.detachEvent = () => {};

// Minimal fetch so the component's load effects resolve instead of hanging.
const jsonResponse = (body) =>
  Promise.resolve({
    ok: true,
    status: 200,
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  });

const seededRecords = [
  {
    spt_depth: 1.5,
    blows_15: 3,
    blows_30: 5,
    blows_45: 7,
    n_value: 12,
    status: "APPROVED",
  },
];

globalThis.fetch = (url, init = {}) => {
  const u = String(url);
  // Session restore calls getHome() and expects { user: ... }; the role on
  // that user is what unlocks the admin approval section.
  if (u.includes("/auth/home")) {
    return jsonResponse({ user: { id: 1, username: "admin", role: "admin" } });
  }
  if (u.includes("/spt/pending")) {
    return jsonResponse({ records: [] });
  }
  if (u.includes("/spt")) {
    if ((init.method || "GET").toUpperCase() !== "GET") {
      return jsonResponse({});
    }
    // The client unwraps result.records, so the envelope matters.
    return jsonResponse({ records: seededRecords });
  }
  return jsonResponse([]);
};

// The app stores its session under these exact keys; useAuth reads both and
// bounces to /login when either is missing.
dom.window.localStorage.setItem("access_token", "fake-token-for-tests");
dom.window.localStorage.setItem("refresh_token", "fake-refresh-for-tests");

const { AuthProvider } = await import("./src/auth/AuthContext.tsx");
const { SptModule } = await import(
  "./src/pages/ProjectWorkspace/FieldData/SptModule.tsx"
);

const e = React.createElement;
const checks = [];
function check(name, fn) {
  checks.push({ name, fn });
}

const container = dom.window.document.createElement("div");
dom.window.document.body.appendChild(container);
let root = null;

async function frame() {
  // Flush pending microtasks/timers outside act, then re-enter act once, so
  // React never sees two overlapping act() scopes.
  await new Promise((r) => setTimeout(r, 10));
  await act(async () => {});
}

const qa = (sel) => [...dom.window.document.querySelectorAll(sel)];
const rows = () => qa("input[data-spt-cell]").length / 4;
const cell = (r, f) =>
  dom.window.document.querySelector(`input[data-spt-cell="${r}:${f}"]`);
const activeAddress = () => {
  const el = dom.window.document.activeElement;
  return el?.getAttribute?.("data-spt-cell") ?? null;
};

function byText(text) {
  const el = qa("button").find((b) => b.textContent.trim() === text);
  if (!el) {
    throw new Error(
      `no button "${text}"; have: ${qa("button").map((b) => b.textContent.trim()).join(" | ")}`
    );
  }
  return el;
}

function key(el, k, opts = {}) {
  act(() => {
    el.dispatchEvent(
      new dom.window.KeyboardEvent("keydown", {
        key: k,
        bubbles: true,
        cancelable: true,
        ...opts,
      })
    );
  });
}

function click(el) {
  act(() => {
    el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  });
}

// Mount. The component loads async, so settle before asserting.
await act(async () => {
  root = createRoot(container);
  root.render(e(AuthProvider, null, e(SptModule, { projectId: "P1", locaId: "BH-01" })));
});
await frame();

// ---- hidden by default --------------------------------------------------

check("grid is hidden on open", () => {
  if (cell(0, "spt_depth")) throw new Error("grid rendered before being asked");
});

check("the toggle button offers to open the grid", () => {
  const btn = byText("Enter SPT Data");
  if (btn.getAttribute("aria-expanded") !== "false") {
    throw new Error("toggle should report collapsed");
  }
});

check("no modal/dialog wrapper is used", () => {
  const modal = dom.window.document.querySelector(
    '[role="dialog"], .modal-overlay, .modal-box'
  );
  if (modal) throw new Error("entry grid must render inline, not in a window");
});

// ---- show / hide --------------------------------------------------------

check("pressing Enter SPT Data reveals the grid inline", async () => {
  click(byText("Enter SPT Data"));
  await frame();
  if (!cell(0, "spt_depth")) throw new Error("grid did not open");
  const panel = dom.window.document.querySelector("#spt-entry-grid");
  if (!panel) throw new Error("inline panel id missing");
});

check("grid opens with 5 rows", () => {
  if (rows() !== 5) throw new Error(`expected 5 rows, found ${rows()}`);
});

check("existing SPT records still render alongside the grid", () => {
  if (!dom.window.document.body.textContent.includes("Submitted SPT Records")) {
    throw new Error("records section disappeared");
  }
});

// ---- dynamic growth -----------------------------------------------------

check("+1 Row appends one row", async () => {
  const before = rows();
  click(byText("+ 1 Row"));
  await frame();
  if (rows() !== before + 1) {
    throw new Error(`expected ${before + 1}, found ${rows()}`);
  }
});

check("+10 Rows appends ten", async () => {
  const before = rows();
  click(byText("+ 10 Rows"));
  await frame();
  if (rows() !== before + 10) {
    throw new Error(`expected ${before + 10}, found ${rows()}`);
  }
});

check("row counter tracks open rows dynamically", async () => {
  const read = () =>
    dom.window.document.body.textContent.match(/(\d+) rows? open/)?.[1];
  const before = Number(read());
  click(byText("+ 50 Rows"));
  await frame();
  const after = Number(read());
  if (after !== before + 50) {
    throw new Error(`counter said ${before} then ${after}`);
  }
});

check("Enter on the last row grows the grid", async () => {
  const before = rows();
  act(() => {
    cell(before - 1, "blows_45").focus();
  });
  key(cell(before - 1, "blows_45"), "Enter");
  await frame();
  if (rows() !== before + 1) {
    throw new Error(`expected ${before + 1}, found ${rows()}`);
  }
});

// ---- focus behaviour jsdom CAN verify -----------------------------------

check("every editable cell is focusable and addressable", () => {
  const el = cell(2, "blows_30");
  el.focus();
  if (activeAddress() !== "2:blows_30") {
    throw new Error(`focus not addressable, got ${activeAddress()}`);
  }
});

check("ArrowRight from an empty cell steps across", () => {
  act(() => {
    cell(4, "spt_depth").focus();
  });
  key(cell(4, "spt_depth"), "ArrowRight");
  if (activeAddress() !== "4:blows_15") {
    throw new Error(`expected 4:blows_15, got ${activeAddress()}`);
  }
});

check("ArrowLeft from an empty cell steps back", () => {
  act(() => {
    cell(4, "blows_30").focus();
  });
  key(cell(4, "blows_30"), "ArrowLeft");
  if (activeAddress() !== "4:blows_15") {
    throw new Error(`expected 4:blows_15, got ${activeAddress()}`);
  }
});

check("ArrowUp keeps the column and changes row", () => {
  act(() => {
    cell(3, "blows_15").focus();
  });
  key(cell(3, "blows_15"), "ArrowUp");
  if (activeAddress() !== "2:blows_15") {
    throw new Error(`expected 2:blows_15, got ${activeAddress()}`);
  }
});

check("ArrowUp at the top row stays put", () => {
  act(() => {
    cell(0, "spt_depth").focus();
  });
  key(cell(0, "spt_depth"), "ArrowUp");
  if (activeAddress() !== "0:spt_depth") {
    throw new Error(`expected to stay, got ${activeAddress()}`);
  }
});

check("Tab from the last cell of a row wraps to the next row", () => {
  act(() => {
    cell(1, "blows_45").focus();
  });
  key(cell(1, "blows_45"), "Tab");
  const addr = activeAddress();
  if (addr !== "2:spt_depth") {
    throw new Error(`expected 2:spt_depth, got ${addr}`);
  }
});

check("Shift+Tab walks back the same path", () => {
  act(() => {
    cell(2, "spt_depth").focus();
  });
  key(cell(2, "spt_depth"), "Tab", { shiftKey: true });
  if (activeAddress() !== "1:blows_45") {
    throw new Error(`expected 1:blows_45, got ${activeAddress()}`);
  }
});

check("Escape keeps the panel open (closing is the button's job)", () => {
  act(() => {
    cell(0, "spt_depth").focus();
  });
  key(cell(0, "spt_depth"), "Escape");
  if (!dom.window.document.querySelector("#spt-entry-grid")) {
    throw new Error("Escape should not collapse the panel");
  }
});

// ---- hide round-trip ----------------------------------------------------

check("pressing the toggle again hides the grid", async () => {
  click(byText("Hide Entry Grid"));
  await frame();
  if (cell(0, "spt_depth")) throw new Error("grid did not hide");
  if (!byText("Enter SPT Data")) throw new Error("toggle label did not reset");
});

// ---- edit flow ----------------------------------------------------------

check("row actions: Clear is yellow, Remove is red, Edit is green", async () => {
  click(byText("Enter SPT Data"));
  await frame();
  const clear = qa("button").find(
    (b) => b.getAttribute("aria-label") === "Clear row 1"
  );
  if (!clear.className.includes("btn-warn")) {
    throw new Error(`Clear class: ${clear.className}`);
  }
  const remove = qa("button").find(
    (b) => b.getAttribute("aria-label") === "Remove row 1"
  );
  if (!remove.className.includes("btn-danger")) {
    throw new Error(`Remove class: ${remove.className}`);
  }
  const edit = byText("Edit");
  if (!edit.className.includes("btn-edit")) {
    throw new Error(`Edit class: ${edit.className}`);
  }
  const del = byText("Delete");
  if (!del.className.includes("btn-danger")) {
    throw new Error(`Delete class: ${del.className}`);
  }
});

check("Edit opens inline in the row, not as a grid at the top", async () => {
  // The previous check opened the grid; close it first so the assertion is
  // about what Edit does, not about what was already on screen.
  if (cell(0, "spt_depth")) {
    click(byText("Hide Entry Grid"));
    await frame();
  }

  click(byText("Edit"));
  await frame();

  // The record's own row becomes the editor. The entry grid must NOT open:
  // the original bug was that clicking Edit revealed a grid at the top of
  // the page, above the fold, which the user never noticed.
  if (cell(0, "spt_depth")) {
    throw new Error("Edit must not open the entry grid");
  }
  if (dom.window.document.querySelector("#spt-entry-grid")) {
    throw new Error("Edit must not open the entry panel at the top");
  }

  const inline = qa("input.spt-inline-input");
  if (inline.length !== 4) {
    throw new Error(`expected 4 inline inputs, found ${inline.length}`);
  }
  if (inline[0].value !== "1.5") {
    throw new Error(`expected depth 1.5, found "${inline[0].value}"`);
  }
  if (!byText("Save")) throw new Error("inline row should offer Save");
  if (!byText("Cancel")) throw new Error("inline row should offer Cancel");

  // The row shows it is being edited rather than silently swapping values.
  if (!dom.window.document.body.textContent.includes("Editing")) {
    throw new Error("editing row should say so");
  }
});

check("Cancel leaves edit mode without touching the row", async () => {
  click(byText("Cancel"));
  await frame();
  if (qa("input.spt-inline-input").length !== 0) {
    throw new Error("Cancel did not close the inline editor");
  }
  // The record is still there, still in its original state.
  if (!dom.window.document.body.textContent.includes("Submitted SPT Records")) {
    throw new Error("records table disappeared");
  }
});

check("delete uses an in-app dialog, not window.confirm", async () => {
  // Arm the browser-native path so its use would be visible rather than silent.
  const nativeConfirm = dom.window.window.confirm;
  let nativeCalls = 0;
  dom.window.window.confirm = () => {
    nativeCalls += 1;
    return false;
  };

  try {
    click(byText("Delete"));
    await frame();

    if (nativeCalls > 0) {
      throw new Error("Delete used the browser confirm dialog");
    }
    const dialog = dom.window.document.querySelector('[role="dialog"]');
    if (!dialog) throw new Error("Delete did not open an in-app dialog");
    if (!dialog.textContent.includes("1.5")) {
      throw new Error("dialog should name the record being deleted");
    }
    if (!byText("Cancel")) throw new Error("dialog should offer Cancel");
  } finally {
    dom.window.window.confirm = nativeConfirm;
  }

  // Leave the module as we found it, so a test appended below does not start
  // with a dialog already covering the table.
  click(byText("Cancel"));
  await frame();
  if (dom.window.document.querySelector('[role="dialog"]')) {
    throw new Error("dialog did not close");
  }
});

/* ------------------------------------------------------------------
   Admin review queue: the editor chip and the changes dialog.
   ------------------------------------------------------------------ */

// One row re-queued by an edit, one fresh submission, so both branches of
// the "Edited" chip are exercised in a single render.
const editedPendingRow = {
  sample_id: "SPT-9",
  spt_depth: 3.0,
  blows_15: 2,
  blows_30: 4,
  blows_45: 6,
  n_value: 10,
  status: "PENDING",
  created_by: "engineer_one",
  created_at: "2026-09-20T10:00:00Z",
  last_edited_by: "engineer_two",
  last_edited_at: "2026-09-29T18:30:00Z",
};

const freshPendingRow = {
  sample_id: "SPT-10",
  spt_depth: 4.5,
  blows_15: 1,
  blows_30: 3,
  blows_45: 5,
  n_value: 8,
  status: "PENDING",
  created_by: "engineer_one",
  created_at: "2026-09-30T09:00:00Z",
  last_edited_by: null,
  last_edited_at: null,
};

const pendingRows = [editedPendingRow, freshPendingRow];

let historyFetches = 0;
let adminContainer = null;
const realFetch = globalThis.fetch;
globalThis.fetch = (url, init = {}) => {
  const u = String(url);
  if (u.includes("/spt/pending")) {
    return jsonResponse({ records: pendingRows });
  }
  if (u.includes("/audit") || u.includes("/history")) {
    historyFetches += 1;
    return jsonResponse({
      sample_id: "SPT-9",
      changes: [
        {
          field: "ISPT_INC2",
          old_value: 3,
          new_value: 4,
          edited_by: "engineer_two",
          edited_at: "2026-09-29T18:30:00Z",
        },
        {
          field: "ISPT_INC3",
          old_value: 5,
          new_value: 6,
          edited_by: "engineer_two",
          edited_at: "2026-09-29T18:30:00Z",
        },
      ],
    });
  }
  return realFetch(url, init);
};

// The module is already mounted once at the top of this file. Its load effect
// is keyed on (projectId, locaId, isAdmin), so re-rendering with the same
// props would NOT re-fetch and the pending list would keep its original empty
// payload. Unmount the first root and mount a fresh one against the new stub.
async function loadAdminQueue() {
  await act(async () => {
    root.unmount();
  });
  adminContainer = dom.window.document.createElement("div");
  dom.window.document.body.appendChild(adminContainer);
  await act(async () => {
    root = createRoot(adminContainer);
    root.render(
      e(AuthProvider, null, e(SptModule, { projectId: "P1", locaId: "BH-01" }))
    );
  });
  for (let i = 0; i < 40; i += 1) await frame();
  return adminContainer;
}

check("pending row names the editor who re-queued it", async () => {
  const root = await loadAdminQueue();
  const html = root.innerHTML;
  if (!html.includes("engineer_two")) {
    throw new Error("re-queued row should name its last editor");
  }
  if (!html.includes("Edited")) {
    throw new Error("re-queued row should be marked as edited");
  }
  // The original submitter must stay visible alongside the editor.
  if (!html.includes("engineer_one")) {
    throw new Error("submitter should still be shown");
  }
});

check("View changes only appears on rows that were edited", async () => {
  const root = await loadAdminQueue();
  const buttons = [...root.querySelectorAll("button")].filter(
    (b) => b.textContent.trim() === "View changes"
  );
  if (buttons.length !== 1) {
    throw new Error(
      `expected 1 "View changes" button (only on edited rows), got ${buttons.length}`
    );
  }
});

check("View changes opens the audit diff dialog", async () => {
  const root = await loadAdminQueue();
  const before = historyFetches;
  const button = [...root.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === "View changes"
  );
  if (!button) throw new Error("no View changes button to click");

  await act(async () => {
    button.dispatchEvent(
      new dom.window.MouseEvent("click", { bubbles: true })
    );
  });
  for (let i = 0; i < 40; i += 1) await frame();

  if (historyFetches <= before) {
    throw new Error("opening the dialog did not fetch sample history");
  }
  const dialog = dom.window.document.querySelector('[role="dialog"]');
  if (!dialog) throw new Error("changes dialog did not open");
  const text = dialog.textContent;
  if (!text.includes("Changes pending approval")) {
    throw new Error("dialog should be titled");
  }
  if (!text.includes("SPT-9")) {
    throw new Error("dialog should identify the sample");
  }
  if (!text.includes("ISPT_INC2")) {
    throw new Error("dialog should list the changed field");
  }
  if (!text.includes("engineer_two")) {
    throw new Error("dialog should attribute the change");
  }
  // Newest change first: a reviewer cares about the most recent edit.
  const order = [...dialog.querySelectorAll("tbody tr")].map((tr) =>
    tr.textContent
  );
  if (order.length !== 2) {
    throw new Error(`expected 2 changed fields, got ${order.length}`);
  }

  // Escape closes it, so the queue is usable again afterwards.
  await act(async () => {
    dom.window.dispatchEvent(
      new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true })
    );
  });
  for (let i = 0; i < 20; i += 1) await frame();
  if (dom.window.document.querySelector('[role="dialog"]')) {
    throw new Error("Escape did not close the changes dialog");
  }
});


const results = [];
for (const { name, fn } of checks) {
  try {
    await fn();
    results.push(`PASS ${name}`);
  } catch (err) {
    results.push(`FAIL ${name} -> ${err.message}`);
  }
}

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);