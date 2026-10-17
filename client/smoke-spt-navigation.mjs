/* Navigation and row-shape verification for the SPT entry grid.
 *
 * This runs against the pure module with real row data, which is the only
 * way to cover the cases that matter: a controlled input cannot be typed
 * into under jsdom, so a DOM-driven test could never reach the state where
 * some depths are filled and others are not - which is exactly the flow the
 * grid has to get right.
 *
 * Row shape is written as a compact string so an expectation reads like the
 * grid looks:
 *     D15 = depth 1.5
 *     _.5 = depth empty, 15cm empty, 30cm = 5
 *     ' ' = blank row
 */

import {
  EDITABLE_FIELDS,
  compact,
  computeN,
  emptyRow,
  firstGapIn,
  isBlank,
  isFilled,
  nextInReadingOrder,
  nextRowStart,
  previousInReadingOrder,
} from "./src/pages/ProjectWorkspace/FieldData/sptGridNavigation.ts";

let failures = 0;
const lines = [];
function check(name, fn) {
  try {
    fn();
    lines.push(`PASS ${name}`);
  } catch (err) {
    failures += 1;
    lines.push(`FAIL ${name} -> ${err.message}`);
  }
}

function assertEq(actual, expected, what) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what}: expected ${b}, got ${a}`);
}

/** row(depth, b15, b30, b45) - undefined means leave empty. */
function row(depth, b15, b30, b45) {
  return {
    spt_depth: depth ?? null,
    blows_15: b15 ?? null,
    blows_30: b30 ?? null,
    blows_45: b45 ?? null,
  };
}

const blank = () => emptyRow();
const blanks = (n) => Array.from({ length: n }, emptyRow);

/** Renders the grid as readable lines. */
function shape(rows) {
  return rows.map((r) => {
    if (isBlank(r)) return "blank";
    return EDITABLE_FIELDS.map((f) => (r[f] === null ? "_" : String(r[f]))).join("|");
  });
}

// ---- the reported bug: depth column keyed first -------------------------

check("depths keyed first: Enter from depth 1 lands on row 2, NOT on a filled depth", () => {
  // The scenario GK described. All depths are already in, so advancing from
  // a depth must skip the next row's depth and land on its 15cm count.
  const rows = [row(1.0, null, null, null), row(2.0, null, null, null)];
  assertEq(nextRowStart(rows, 0), { row: 1, field: "blows_15" }, "next row target");
});

check("Enter lands on a blank row's depth (a blank row belongs to nobody)", () => {
  const rows = [row(1.0, 3, 5, 7), blanks(1)[0], row(3.0, null, null, null)];
  // Row 1 is empty, so its first gap really is its depth. Skipping it would
  // silently leave the blank row unkeyed.
  assertEq(nextRowStart(rows, 0), { row: 1, field: "spt_depth" }, "blank row is usable");
});

check("Enter skips a fully-keyed row to reach one with a gap", () => {
  const rows = [row(1.0, null, null, null), row(2.0, 4, 6, 8), row(3.0, null, null, null)];
  assertEq(nextRowStart(rows, 0), { row: 2, field: "blows_15" }, "skips filled row");
});

check("Enter picks the leftmost gap, not just the 15cm column", () => {
  // 15cm already keyed, so the row's first gap is its 30cm count.
  const rows = [row(1.0, null, null, null), row(2.0, 5, null, null)];
  assertEq(nextRowStart(rows, 0), { row: 1, field: "blows_30" }, "leftmost gap");
});

check("Enter returns null at the last row so the caller can grow", () => {
  const rows = [row(1.0, null, null, null)];
  assertEq(nextRowStart(rows, 0), null, "no room left");
});

check("Enter with a partially keyed row below lands on that row's gap", () => {
  // Row 1 has depth + 15cm, so its first gap is 30cm.
  const rows = [row(1.0, 3, 8, 9), row(2.0, 4, null, null)];
  assertEq(nextRowStart(rows, 0), { row: 1, field: "blows_30" }, "partial row gap");
});

// ---- Tab: strict reading order -----------------------------------------

check("Tab goes left to right across the row", () => {
  const rows = [blank()];
  assertEq(nextInReadingOrder(rows, 0, 0), { row: 0, field: "blows_15" }, "across");
  assertEq(nextInReadingOrder(rows, 0, 1), { row: 0, field: "blows_30" }, "across");
  assertEq(nextInReadingOrder(rows, 0, 2), { row: 0, field: "blows_45" }, "across");
});

check("Tab wraps from the last column to the next row's first column", () => {
  const rows = blanks(2);
  assertEq(nextInReadingOrder(rows, 0, 3), { row: 1, field: "spt_depth" }, "wrap");
});

check("Tab never lands on the current cell (fresh grid is all empty)", () => {
  // The regression that made Enter and Tab look dead: every cell in a new
  // grid is empty, so the scan must start past the caret.
  const rows = blanks(3);
  const t = nextInReadingOrder(rows, 0, 0);
  if (t.row === 0 && t.field === "spt_depth") {
    throw new Error("landed on the cell the caret is already in");
  }
});

check("Shift+Tab walks back over the same path Tab walked forward", () => {
  const rows = blanks(2);
  assertEq(previousInReadingOrder(rows, 1, 0), { row: 0, field: "blows_45" }, "back");
  assertEq(previousInReadingOrder(rows, 0, 2), { row: 0, field: "blows_15" }, "back");
});

// The regression: Tab skipped filled cells, Shift+Tab did not, so Tab right
// N times then Shift+Tab N times did not return to the start. Every test above
// uses a blank grid, where the two rules happen to agree -- which is why this
// went unnoticed. These use a partially filled one.
check("Tab does NOT skip a cell that already holds a value", () => {
  const rows = [row({ spt_depth: 1.5, blows_15: 1 }), blank()];
  assertEq(
    nextInReadingOrder(rows, 0, 1),
    { row: 0, field: "blows_30" },
    "Tab must step into the filled blows_30, not jump past it"
  );
});

check("Shift+Tab is the exact inverse of Tab on a filled grid", () => {
  const rows = [
    row({ spt_depth: 1.5, blows_15: 1, blows_30: 2 }),
    row({ spt_depth: 3.0, blows_15: 1 }),
    blank(),
  ];
  // Walk forward eight cells, then back eight, and expect to be home.
  let r = 0;
  let c = 0;
  for (let i = 0; i < 8; i += 1) {
    const t = nextInReadingOrder(rows, r, c);
    if (!t) throw new Error(`ran off the grid going forward at step ${i}`);
    r = t.row;
    c = EDITABLE_FIELDS.indexOf(t.field);
  }
  for (let i = 0; i < 8; i += 1) {
    const t = previousInReadingOrder(rows, r, c);
    if (!t) throw new Error(`ran off the grid going back at step ${i}`);
    r = t.row;
    c = EDITABLE_FIELDS.indexOf(t.field);
  }
  assertEq({ row: r, field: EDITABLE_FIELDS[c] }, { row: 0, field: "spt_depth" }, "home again");
});

check("Tab and Shift+Tab agree cell-for-cell across a row boundary", () => {
  const rows = [row({ spt_depth: 1.5, blows_30: 2 }), row({ spt_depth: 3.0 }), blank()];
  // Forward from the last column of row 0...
  const forward = nextInReadingOrder(rows, 0, 3);
  assertEq(forward, { row: 1, field: "spt_depth" }, "wrap forward");
  // ...and back from that cell lands on the last column of row 0.
  const back = previousInReadingOrder(rows, forward.row, 0);
  assertEq(back, { row: 0, field: "blows_45" }, "wrap back");
});

check("Enter still jumps to the next cell that needs a value", () => {
  // The skip-filled behaviour is not lost, it belongs to Enter/Down.
  const rows = [row({ spt_depth: 1.5, blows_15: 1 }), row({ spt_depth: 3.0 })];
  assertEq(nextRowStart(rows, 0), { row: 1, field: "blows_15" }, "Enter target");
});

check("Shift+Tab at the very first cell returns null", () => {
  assertEq(previousInReadingOrder(blanks(2), 0, 0), null, "start of grid");
});

// ---- row shape ---------------------------------------------------------

check("firstGapIn: a depths-only row's first gap is its 15cm count", () => {
  assertEq(firstGapIn(row(1.0, null, null, null)), "blows_15", "gap");
});

check("firstGapIn: a fully keyed row has no gap", () => {
  assertEq(firstGapIn(row(1.0, 3, 5, 7)), null, "no gap");
});

check("firstGapIn: partial row reports its leftmost gap", () => {
  assertEq(firstGapIn(row(1.0, 3, 5, null)), "blows_45", "gap");
});

check("isBlank only for a completely empty row", () => {
  if (!isBlank(blank())) throw new Error("blank row not blank");
  if (isBlank(row(1.0, null, null, null))) {
    throw new Error("a row with a depth is not blank");
  }
});

check("isFilled needs depth plus both counts N is derived from", () => {
  if (isFilled(row(1.0, 3, null, 7))) {
    throw new Error("missing 30cm should not count as filled");
  }
  if (!isFilled(row(1.0, 3, 5, 7))) {
    throw new Error("complete row should count as filled");
  }
});

check("computeN is the plain sum of the 30cm and 45cm counts", () => {
  assertEq(computeN(row(1, 2, 5, 7)), 12, "N");
  assertEq(computeN(row(1, 2, 5, null)), null, "incomplete N");
});

// ---- compaction --------------------------------------------------------

check("compact lifts a finished row above the blanks", () => {
  // Keying several rows down leaves gaps at the top; the log must still read
  // top-down.
  const rows = [blank(), blank(), row(3.0, 4, 6, 8)];
  assertEq(shape(compact(rows)), ["3|4|6|8", "blank", "blank"], "lifted to top");
});

check("compact leaves an already-ordered grid untouched", () => {
  const rows = [row(1.0, 4, 6, 8), blank(), blank()];
  assertEq(shape(compact(rows)), ["1|4|6|8", "blank", "blank"], "unchanged");
});

check("compact does not move a row that is only partly keyed", () => {
  // Depths-only rows are not finished, so they must not be shuffled up.
  const rows = [blank(), row(2.0, null, null, null)];
  assertEq(shape(compact(rows)), ["blank", "2|_|_|_"], "partly keyed stays put");
});

check("compact gathers every finished row to the top, in original order", () => {
  // The reported bug: two finished rows with a gap between them used to move
  // only one, leaving the other stranded below a blank row.
  const rows = [blank(), row(2.0, 4, 6, 8), blank(), row(4.0, 5, 7, 9)];
  assertEq(
    shape(compact(rows)),
    ["2|4|6|8", "4|5|7|9", "blank", "blank"],
    "both lifted, order kept"
  );
});

check("compact does not shuffle part-keyed rows during depth-first entry", () => {
  // Depths keyed top to bottom, then blows filled in on row 1. The grid must
  // not rearrange itself mid-entry.
  const rows = [row(1.0, null, null, null), row(2.0, 3, 5, 7), row(3.0, null, null, null)];
  assertEq(shape(compact(rows)), shape(rows), "left alone while keying");
});

check("compact on an all-blank grid changes nothing", () => {
  const rows = blanks(4);
  assertEq(shape(compact(rows)), shape(rows), "no-op");
});

check("compact is stable and idempotent", () => {
  const rows = [blank(), row(2.0, 4, 6, 8), row(3.0, 5, 7, 9)];
  const once = compact(rows);
  const twice = compact(once);
  assertEq(shape(once), shape(twice), "idempotent");
});

console.log(lines.join("\n"));
console.log(`\n${lines.length - failures}/${lines.length} passed`);
process.exit(failures === 0 ? 0 : 1);