/* Regression tests for the unsaved-changes guard's decision logic.
 *
 * The failure this prevents is silent: a grid holds typed rows in component
 * state, the workspace unmounts it on a tab change, and the typing is gone
 * with no prompt. These cover the part that decides *whether* to prompt and
 * *what it says*; the React wiring around them is covered by tsc and build.
 *
 * Runs on plain node via tsx, matching smoke-spt-navigation.mjs. jsdom is
 * not a dependency here, so nothing in this file touches the DOM.
 */
import {
  reportDirty,
  dirtyLabels,
  buildDiscardMessage,
} from "./src/pages/ProjectWorkspace/unsavedChangesLogic.ts";

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);
const eq = (name, actual, expected) =>
  results.push(
    `${actual === expected ? "PASS" : "FAIL"} ${name}` +
      (actual === expected ? "" : ` (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`)
  );

let reg = {};

// --- register / withdraw -------------------------------------------------
reg = reportDirty(reg, "spt", "SPT entry grid", true);
eq("one dirty surface reports one label", dirtyLabels(reg).length, 1);
eq("label is the registered one", dirtyLabels(reg)[0], "SPT entry grid");

// Re-reporting the same state must not produce a new object, otherwise a
// component that reports on every render loops forever.
const sameRef = reportDirty(reg, "spt", "SPT entry grid", true);
check("idempotent report returns the same reference", sameRef === reg);

// Two grids at once is a real case (switch borehole without submitting).
const both = reportDirty(reg, "rock", "Rock entry grid", true);
eq("two dirty surfaces report two labels", dirtyLabels(both).length, 2);

// Withdrawing one leaves the other alone.
const withdrewSpt = reportDirty(both, "spt", "SPT entry grid", false);
eq("withdrawing one leaves the other", dirtyLabels(withdrewSpt).join(","), "Rock entry grid");

// Withdrawing something never registered is a no-op, not a crash. This is
// the unmount path firing for a grid that had nothing to save.
const phantom = reportDirty(both, "never-dirty", "Borehole", false);
check("withdrawing an unregistered surface is safe", phantom === both);
eq("phantom withdrawal did not change labels", dirtyLabels(phantom).length, 2);

// Empty registry => no prompt at all.
check("clean registry produces no message", buildDiscardMessage(dirtyLabels({})) === null);

// --- prompt text ---------------------------------------------------------
const single = buildDiscardMessage(["SPT entry grid"]);
check("single-dirty prompt is produced", typeof single === "string");
check("single-dirty prompt names the grid", single.includes("SPT entry grid"));
check("single-dirty prompt says 'it', not 'them'", single.includes("discard it."));
check("single-dirty prompt does not use the plural count", !single.includes("1 grids"));

const multi = buildDiscardMessage(["SPT entry grid", "Rock entry grid"]);
check("multi-dirty prompt counts the grids", multi.includes("2 grids"));
check("multi-dirty prompt says 'them'", multi.includes("discard them."));

// Both prompts must make the consequence explicit -- that the rows are not
// saved anywhere yet. Without that sentence the user cannot tell whether
// cancelling is safe.
for (const [name, msg] of [["single", single], ["multi", multi]]) {
  check(
    `${name} prompt states rows are not persisted`,
    msg.includes("not been submitted to the database")
  );
}

// A grid that reports clean during an in-flight submit must not nag, because
// the data is being persisted right then.
const submitting = reportDirty(reg, "spt", "SPT entry grid", false);
check("submitting clears the warning", buildDiscardMessage(dirtyLabels(submitting)) === null);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);