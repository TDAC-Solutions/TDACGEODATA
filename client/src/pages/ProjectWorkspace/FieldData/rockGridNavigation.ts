/**
 * Keyboard navigation for the Rock entry grid.
 *
 * SPT already has this (see sptGridNavigation.ts) and Rock was left behind,
 * so keying a long run meant reaching for the mouse on every cell. This is
 * the same idea over a grid that is slightly harder: Rock rows carry a
 * variable number of Block Number boxes, so "the cell below" is not always
 * the same piece index -- the row underneath may have fewer pieces, or none.
 *
 * Kept out of the component, like sptGridNavigation, because the interesting
 * cases are about row shape (how many pieces each row has) and that is far
 * easier to pin down here than through a DOM. A controlled input cannot be
 * typed into under jsdom, which is exactly why sptGridNavigation exists.
 */

/**
 * Editable columns, in the order they read across a row. Recovery and RQD
 * are deliberately absent: they are derived, so they are never focusable.
 */
export const ROCK_COLUMNS = [
  "depth_from",
  "depth_to",
  "rock_type",
  "lift_no",
  "pieces",
] as const;

export type RockColumn = (typeof ROCK_COLUMNS)[number];

/** Column index of the Block Number boxes. */
export const PIECE_COLUMN = 4;

/** Sentinel for the single-input columns, which have no piece index. */
export const NO_PIECE = -1;

export interface RockCell {
  row: number;
  col: number;
  piece: number;
}

/** How many Block Number boxes a row currently has. */
export type PieceCounts = readonly number[];

/** Stable key used to find the input for a cell in the DOM. */
export function cellKey(
  row: number,
  col: number,
  piece: number = NO_PIECE
): string {
  return `${row}:${col}:${piece}`;
}

/** Every focusable cell in one row, left to right. */
export function cellsInRow(row: number, pieceCount: number): RockCell[] {
  const cells: RockCell[] = [];
  for (let col = 0; col < PIECE_COLUMN; col += 1) {
    cells.push({ row, col, piece: NO_PIECE });
  }
  for (let piece = 0; piece < pieceCount; piece += 1) {
    cells.push({ row, col: PIECE_COLUMN, piece });
  }
  return cells;
}

export function firstCellOfRow(cell: RockCell): RockCell {
  return { row: cell.row, col: 0, piece: NO_PIECE };
}

export function lastCellOfRow(
  row: number,
  pieceCount: number
): RockCell {
  if (pieceCount > 0) {
    return { row, col: PIECE_COLUMN, piece: pieceCount - 1 };
  }
  return { row, col: PIECE_COLUMN - 1, piece: NO_PIECE };
}

/**
 * True when the target row actually has that cell.
 *
 * A piece index only exists if the row has that many pieces, which is the
 * whole difficulty here: Block 3 of the row below may simply not exist.
 */
export function hasCell(counts: PieceCounts, cell: RockCell): boolean {
  if (cell.row < 0 || cell.row >= counts.length) return false;
  if (cell.col === PIECE_COLUMN) return cell.piece < counts[cell.row];
  return true;
}

/**
 * Re-home a piece index onto a row that may hold fewer boxes.
 *
 * Moving down from Block 3 into a row with two pieces lands on Block 2
 * rather than nowhere: the engineer is still moving down a column, they just
 * ran out of boxes.
 */
export function clampToRow(
  counts: PieceCounts,
  cell: RockCell
): RockCell | null {
  if (cell.row < 0 || cell.row >= counts.length) return null;
  if (cell.col !== PIECE_COLUMN || cell.piece === NO_PIECE) return cell;

  const available = counts[cell.row];
  if (available <= 0) {
    // No pieces in that row: fall back to the cell before the pieces column.
    return { row: cell.row, col: PIECE_COLUMN - 1, piece: NO_PIECE };
  }
  return { row: cell.row, col: PIECE_COLUMN, piece: Math.min(cell.piece, available - 1) };
}

/** Same column and piece, one row down. */
export function cellBelow(counts: PieceCounts, cell: RockCell): RockCell | null {
  return clampToRow(counts, { ...cell, row: cell.row + 1 });
}

/** Same column and piece, one row up. */
export function cellAbove(counts: PieceCounts, cell: RockCell): RockCell | null {
  if (cell.row === 0) return null;
  return clampToRow(counts, { ...cell, row: cell.row - 1 });
}

/**
 * The next focusable cell after this one, scanning left to right then top to
 * bottom -- what Tab walks. Shift+Tab walks the same path back.
 */
export function nextInReadingOrder(
  counts: PieceCounts,
  cell: RockCell
): RockCell | null {
  const from = cellsInRow(cell.row, counts[cell.row] ?? 0);
  const index = from.findIndex(
    (c) => c.col === cell.col && c.piece === cell.piece
  );
  if (index !== -1 && index + 1 < from.length) return from[index + 1];

  for (let row = cell.row + 1; row < counts.length; row += 1) {
    const next = cellsInRow(row, counts[row]);
    if (next.length > 0) return next[0];
  }
  return null;
}

export function previousInReadingOrder(
  counts: PieceCounts,
  cell: RockCell
): RockCell | null {
  // Within the starting row the cell before this one is the answer, so the
  // scan starts immediately to its left. Scanning from the row's end instead
  // would hand back the cells to the right, which is the wrong direction.
  const here = cellsInRow(cell.row, counts[cell.row] ?? 0);
  const index = here.findIndex(
    (c) => c.col === cell.col && c.piece === cell.piece
  );
  if (index > 0) return here[index - 1];

  // At the start of the row, so step up to wherever the previous row ended.
  // Rows hold different numbers of blocks, hence the per-row last cell.
  for (let row = cell.row - 1; row >= 0; row -= 1) {
    const inRow = cellsInRow(row, counts[row]);
    if (inRow.length > 0) return inRow[inRow.length - 1];
  }
  return null;
}