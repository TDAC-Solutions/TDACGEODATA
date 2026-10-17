/* Regression guards for the audit fixes in this round.
 *
 * These assert the properties behind each bug, because the behaviour itself
 * needs a full render of a populated workspace.
 *
 * 1. Rock inline edit: RockFieldCells is also used for the edit row of an
 *    already-submitted record. That call site passed neither rowIndex nor
 *    onKeyDown, so the component's internal handleKey ran
 *    `onKeyDown?.(event, cell)` against undefined -- a no-op -- and tag()
 *    returned undefined, leaving the cells with no data-cell at all. Tab and
 *    the arrows did nothing in edit mode while working everywhere else.
 *
 * 2. The inline handler must not reuse handleRockKeyDown: that one falls
 *    through to growGridAndFocus, which would append a row to the ENTRY grid
 *    while the engineer was editing a record already submitted. That was the
 *    danger in the audit's suggested `rowIndex={-1}` fix.
 *
 * 3. Results Entry registered no dirty state at all.
 *
 * 4. The Test Register tables were the only bare <table> in the app, so the
 *    stacked-card layout scoped to .dtable never applied to them, and
 *    data-label was absent as well.
 */
import { readFileSync } from "node:fs";

const rock = readFileSync(
  "src/pages/ProjectWorkspace/FieldData/RockModule.tsx",
  "utf8"
);
const resultsEntry = readFileSync(
  "src/pages/ProjectWorkspace/LabData/tabs/ResultsEntryTab.tsx",
  "utf8"
);
const testRegister = readFileSync(
  "src/pages/ProjectWorkspace/LabData/tabs/TestRegisterTab.tsx",
  "utf8"
);

const results = [];
const check = (name, cond) => results.push(`${cond ? "PASS" : "FAIL"} ${name}`);

// --- 1 & 2: Rock inline edit ------------------------------------------
const inlineCall = rock.slice(rock.indexOf("{isEditing && editDraft ? ("));
const hasInlineCall = inlineCall.length > 0;
check("found the inline-edit render branch", hasInlineCall);

if (hasInlineCall) {
  check(
    "inline edit passes a rowIndex so cells get data-cell tags",
    /rowIndex=\{/.test(inlineCall.slice(0, 1200))
  );
  check(
    "inline edit passes onKeyDown so the handler is not a no-op",
    /onKeyDown=\{handleInlineKeyDown\}/.test(inlineCall.slice(0, 1200))
  );
  check(
    "inline edit does NOT reuse the entry-grid handler",
    !/onKeyDown=\{handleRockKeyDown\}/.test(inlineCall.slice(0, 1200))
  );
}

// --- 2: the handler itself must stay inside the inline row --------------
const inlineHandler = rock.slice(
  rock.indexOf("function handleInlineKeyDown"),
  rock.indexOf("function focusRockCell")
);
check("found handleInlineKeyDown", inlineHandler.length > 0);
for (const forbidden of [
  "growGridAndFocus",
  "clearGridRow",
  "cellBelow",
  "cellAbove",
]) {
  check(
    `inline handler never calls ${forbidden} (it would act on the entry grid)`,
    !inlineHandler.includes(forbidden)
  );
}
check(
  "inline handler uses the reading-order helpers for Tab",
  inlineHandler.includes("nextInReadingOrder") &&
    inlineHandler.includes("previousInReadingOrder")
);
check(
  "inline handler focuses through the submitted-table ref",
  rock.includes("inlineRef") && rock.includes("focusInlineCell")
);

// --- 3: Results Entry dirty state --------------------------------------
check(
  "ResultsEntryTab registers with the unsaved guard",
  resultsEntry.includes("useUnsavedChanges")
);
check(
  "Results Entry imports the hook",
  resultsEntry.includes('from "../../UnsavedChanges"')
);
check(
  "dirty is a real diff against a loaded baseline",
  resultsEntry.includes("editableState !== baselineRef.current")
);
check(
  "baseline is refreshed on load, not on every keystroke",
  resultsEntry.includes("loadedTestRef") &&
    resultsEntry.includes("loadedId === loadedTestRef.current")
);
check(
  "the placeholder `= true` from the audit is not what shipped",
  !/hasUnsavedResults\s*=\s*true/.test(resultsEntry)
);

// --- 4: Test Register tables -------------------------------------------
const bareTables = (testRegister.match(/<table>/g) || []).length;
check(
  "no bare <table> left in the Test Register",
  bareTables === 0,
  bareTables === 0 ? "" : `${bareTables} remaining`
);
check(
  "both tables carry .dtable so the mobile card layout applies",
  (testRegister.match(/className="dtable"/g) || []).length === 2
);
const labelledCells = (testRegister.match(/data-label=/g) || []).length;
check(
  "every register cell carries a data-label",
  labelledCells === 11,
  labelledCells === 11 ? "" : `found ${labelledCells}, expected 11`
);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL")).length;
console.log(`\n${results.length - failed}/${results.length} passed`);
process.exit(failed === 0 ? 0 : 1);