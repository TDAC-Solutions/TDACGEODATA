import type { SptRow } from "../../../api/fieldData";

/**
 * Pure navigation and shape logic for the SPT entry grid.
 *
 * Kept out of the component so it can be tested with real data. The grid's
 * tricky behaviour is all in here: where a keystroke lands, and how rows
 * settle once they are filled. Driving those through a DOM was the wrong
 * test surface - a controlled input cannot be typed into under jsdom, so
 * the interesting cases were the ones that could not be covered.
 */

// Five blank rows is enough to start; the grid grows from there.
export const INITIAL_ROWS = 5;

// The only landable cells. SPTN is computed, never typed.
export const EDITABLE_FIELDS = [
  "spt_depth",
  "blows_15",
  "blows_30",
  "blows_45",
] as const satisfies readonly (keyof SptRow)[];

export type EditableField = (typeof EDITABLE_FIELDS)[number];

export interface CellRef {
  row: number;
  field: EditableField;
}

export function emptyRow(): SptRow {
  return { spt_depth: null, blows_15: null, blows_30: null, blows_45: null };
}

// SPTN = Below 30 + Below 45 (plain sum - not averaged or divided).
export function computeN(row: SptRow): number | null {
  const { blows_30, blows_45 } = row;
  if (blows_30 === null || blows_30 === undefined) return null;
  if (blows_45 === null || blows_45 === undefined) return null;
  return blows_30 + blows_45;
}

export function isBlank(row: SptRow): boolean {
  return EDITABLE_FIELDS.every((field) => {
    const value = row[field];
    return value === null || value === undefined;
  });
}

// A row is "filled" when it can actually be submitted: it has a depth plus
// the two counts N-value is derived from.
export function isFilled(row: SptRow): boolean {
  return (
    row.spt_depth !== null &&
    row.spt_depth !== undefined &&
    row.blows_30 !== null &&
    row.blows_30 !== undefined &&
    row.blows_45 !== null &&
    row.blows_45 !== undefined
  );
}

export function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

/**
 * The leftmost cell in a row that still needs a value, or null when the row
 * is fully keyed. This is what "the next row's unfilled column" means: once
 * depths are in, a row's first gap is its 15 cm count, not its depth.
 */
export function firstGapIn(row: SptRow): EditableField | null {
  for (const field of EDITABLE_FIELDS) {
    const value = row[field];
    if (value === null || value === undefined) return field;
  }
  return null;
}

/**
 * The next row below that still has a gap, landing on that row's leftmost
 * gap. Fully keyed rows are skipped, so moving between rows never parks the
 * caret on a cell that is already filled.
 *
 * This is the Enter / Down target, and the reason a log can be keyed by
 * filling the depth column first and then coming back for the blow counts.
 */
export function nextRowStart(
  rows: readonly SptRow[],
  rowIndex: number
): CellRef | null {
  for (let r = rowIndex + 1; r < rows.length; r += 1) {
    const gap = firstGapIn(rows[r]);
    if (gap) return { row: r, field: gap };
  }
  return null;
}

/**
 * Reading-order target: the next unfilled cell AFTER the current one,
 * scanning left-to-right then top-to-bottom.
 *
 * The scan has to start past the current cell. Every cell in a fresh grid is
 * empty, so "first gap in this row" would be the cell you are already
 * standing in and the key would appear dead.
 */
export function nextInReadingOrder(
  rows: readonly SptRow[],
  rowIndex: number,
  colIndex: number
): CellRef | null {
  // Exactly one cell forward, filled or not.
  //
  // This used to skip cells that already held a value, which made Tab and
  // Shift+Tab disagree: Tab skipped over the filled cells on the way right,
  // but Shift+Tab stepped one column at a time on the way back, so Tab five
  // times then Shift+Tab five times did not return to where you started.
  // Shift+Tab is only "undo my last Tab" if Tab is a plain walk.
  //
  // Jumping to the next cell that still needs a value is what Enter and Down
  // are for, and that is nextRowStart's job, not this one.
  if (colIndex + 1 < EDITABLE_FIELDS.length) {
    return { row: rowIndex, field: EDITABLE_FIELDS[colIndex + 1] };
  }

  // Past the last column: continue on the next row's first column.
  if (rowIndex + 1 < rows.length) {
    return { row: rowIndex + 1, field: EDITABLE_FIELDS[0] };
  }
  return null;
}

/**
 * Reverse reading order, the mirror of nextInReadingOrder. Used by
 * Shift+Tab so walking back follows the path Tab walked forward.
 */
export function previousInReadingOrder(
  rows: readonly SptRow[],
  rowIndex: number,
  colIndex: number
): CellRef | null {
  for (let r = rowIndex; r >= 0; r -= 1) {
    // Cells already ahead of the caret in the starting row are behind it in
    // reading order, so start one to the left when on that row.
    const from = r === rowIndex ? colIndex - 1 : EDITABLE_FIELDS.length - 1;
    if (from >= 0) return { row: r, field: EDITABLE_FIELDS[from] };
  }
  return null;
}

/**
 * Pull a completed row up past the empty rows above it.
 *
 * Keying 3-4 rows down then finishing one leaves a gap at the top and the log
 * reads out of order. Stable: only the first filled row below the first blank
 * one moves, and everything else keeps its relative order.
 */
export function compact(rows: readonly SptRow[]): SptRow[] {
  const next = [...rows];

  // One pass moves one row, so a grid with several finished rows separated by
  // gaps needs the lift repeated until it settles. A single pass used to stop
  // early and leave a finished row stranded below a blank one.
  for (;;) {
    const firstBlank = next.findIndex(isBlank);
    if (firstBlank === -1) return next;

    // Lift a finished row only through empty space. A part-keyed row is a
    // barrier rather than a donor: it is work in progress, and shifting it
    // while the user is typing in it is worse than leaving a gap.
    let donor = -1;
    for (let i = firstBlank + 1; i < next.length; i += 1) {
      if (isBlank(next[i])) continue;
      if (isFilled(next[i])) donor = i;
      break;
    }
    if (donor === -1) return next;

    const [moved] = next.splice(donor, 1);
    next.splice(firstBlank, 0, moved);
  }
}