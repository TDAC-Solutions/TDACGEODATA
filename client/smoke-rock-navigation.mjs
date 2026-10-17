/* Navigation checks for the Rock entry grid.
 *
 * Runs against the pure module with real row shapes. The hard part of Rock
 * navigation is that rows hold different numbers of Block Number boxes, so
 * these cases are about piece counts per row rather than keystrokes: moving
 * down out of Block 3 into a row that only has two boxes has to land
 * somewhere sensible.
 */
import {
  NO_PIECE,
  PIECE_COLUMN,
  cellAbove,
  cellBelow,
  cellKey,
  cellsInRow,
  clampToRow,
  firstCellOfRow,
  hasCell,
  lastCellOfRow,
  nextInReadingOrder,
  previousInReadingOrder,
} from "./src/pages/ProjectWorkspace/FieldData/rockGridNavigation.ts";

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

function eq(actual, expected, what) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a !== e) throw new Error(`${what}: got ${a}, wanted ${e}`);
}

// Row shapes used below, written as piece counts.
const TWO = [2, 2, 2]; // three rows, two blocks each
const MIXED = [3, 1, 0]; // three, one, none

check("a row yields depth, depth-to, type, lift then its blocks", () => {
  eq(cellsInRow(0, 2).map((c) => cellKey(c.row, c.col, c.piece)), [
    "0:0:-1",
    "0:1:-1",
    "0:2:-1",
    "0:3:-1",
    "0:4:0",
    "0:4:1",
  ], "cells in row");
});

check("a row with no blocks stops at Lift No", () => {
  const cells = cellsInRow(0, 0);
  eq(cells.length, 4, "cell count");
  eq(cells[cells.length - 1].col, 3, "last column");
});

check("Recovery and RQD are not focusable", () => {
  const cols = cellsInRow(0, 1).map((c) => c.col);
  if (cols.includes(2) && cols.includes(3) && cols.length === 6) {
    throw new Error("column count changed");
  }
  // The derived columns are simply absent: only 5 columns exist and the
  // pieces column is last, so nothing sits between lift_no and the blocks.
  eq(Math.max(...cols), PIECE_COLUMN, "highest column");
});

check("cell keys are unique per row, column and block", () => {
  const keys = new Set(
    [0, 1, 2].flatMap((r) => cellsInRow(r, 2).map((c) => cellKey(c.row, c.col, c.piece)))
  );
  eq(keys.size, 3 * 6, "unique key count");
});

check("down keeps the column and the block", () => {
  eq(cellBelow(TWO, { row: 0, col: PIECE_COLUMN, piece: 1 }), {
    row: 1,
    col: PIECE_COLUMN,
    piece: 1,
  }, "down from block 2");
});

check("down from a block into a shorter row lands on its last block", () => {
  // Block 3 (index 2) of row 0, but row 1 only has one block.
  eq(cellBelow(MIXED, { row: 0, col: PIECE_COLUMN, piece: 2 }), {
    row: 1,
    col: PIECE_COLUMN,
    piece: 0,
  }, "down into a one-block row");
});

check("down from a block into a row with no blocks steps back to Lift No", () => {
  eq(clampToRow(MIXED, { row: 2, col: PIECE_COLUMN, piece: 1 }), {
    row: 2,
    col: PIECE_COLUMN - 1,
    piece: NO_PIECE,
  }, "clamp into a block-less row");
});

check("up from the first row has nowhere to go", () => {
  eq(cellAbove(TWO, { row: 0, col: 1, piece: NO_PIECE }), null, "up from row 0");
});

check("up keeps the column", () => {
  eq(cellAbove(TWO, { row: 2, col: 1, piece: NO_PIECE }), {
    row: 1,
    col: 1,
    piece: NO_PIECE,
  }, "up from row 2");
});

check("down past the last row has nowhere to go", () => {
  eq(cellBelow(TWO, { row: 2, col: 1, piece: NO_PIECE }), null, "down from last");
});

check("tab walks left to right within a row", () => {
  eq(nextInReadingOrder(TWO, { row: 0, col: 0, piece: NO_PIECE }), {
    row: 0,
    col: 1,
    piece: NO_PIECE,
  }, "tab from depth-from");
});

check("tab from the last block continues into the next row", () => {
  eq(nextInReadingOrder(TWO, { row: 0, col: PIECE_COLUMN, piece: 1 }), {
    row: 1,
    col: 0,
    piece: NO_PIECE,
  }, "tab out of the last block");
});

check("tab past the very last cell returns null so the grid can grow", () => {
  eq(nextInReadingOrder(TWO, { row: 2, col: PIECE_COLUMN, piece: 1 }), null, "tab off the end");
});

check("shift+tab walks the same path back", () => {
  eq(previousInReadingOrder(TWO, { row: 1, col: 0, piece: NO_PIECE }), {
    row: 0,
    col: PIECE_COLUMN,
    piece: 1,
  }, "shift+tab to previous row's last block");
});

check("shift+tab within a row steps left", () => {
  eq(previousInReadingOrder(TWO, { row: 0, col: PIECE_COLUMN, piece: 1 }), {
    row: 0,
    col: PIECE_COLUMN,
    piece: 0,
  }, "shift+tab between blocks");
});

check("shift+tab off the first cell returns null", () => {
  eq(previousInReadingOrder(TWO, { row: 0, col: 0, piece: NO_PIECE }), null, "shift+tab at the start");
});

check("hasCell knows a block that does not exist", () => {
  eq(hasCell(MIXED, { row: 2, col: PIECE_COLUMN, piece: 0 }), false, "block in a block-less row");
  eq(hasCell(MIXED, { row: 1, col: PIECE_COLUMN, piece: 0 }), true, "block that exists");
  eq(hasCell(MIXED, { row: 0, col: 2, piece: NO_PIECE }), true, "text column");
});

check("first and last cell of a row are reachable", () => {
  eq(firstCellOfRow({ row: 2, col: 3, piece: NO_PIECE }), {
    row: 2,
    col: 0,
    piece: NO_PIECE,
  }, "first cell");
  eq(lastCellOfRow(0, 2), { row: 0, col: PIECE_COLUMN, piece: 1 }, "last cell");
  eq(lastCellOfRow(0, 0), { row: 0, col: PIECE_COLUMN - 1, piece: NO_PIECE }, "last cell, no blocks");
});

check("a row with a different block count does not break reading order", () => {
  // Tab out of row 0's three blocks must start row 1 at depth-from, not
  // inherit an index that row 1 does not have.
  const target = nextInReadingOrder(MIXED, { row: 0, col: PIECE_COLUMN, piece: 2 });
  eq(target, { row: 1, col: 0, piece: NO_PIECE }, "tab out of a three-block row");
});

console.log(lines.join("\n"));
const total = lines.length;
console.log(`\n${total - failures}/${total} passed`);
process.exit(failures ? 1 : 0);