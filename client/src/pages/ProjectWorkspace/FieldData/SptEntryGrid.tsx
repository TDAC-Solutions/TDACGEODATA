import { useEffect, useMemo, useRef, useState } from "react";
import {
  submitSptRecords,
  updateSptRecord,
  type SptRecord,
  type SptRow,
} from "../../../api/fieldData";
import { useUnsavedChanges } from "../UnsavedChanges";
import {
  EDITABLE_FIELDS,
  INITIAL_ROWS,
  compact,
  computeN,
  emptyRow,
  formatNumber,
  isBlank,
  isFilled,
  nextInReadingOrder,
  nextRowStart,
  previousInReadingOrder,
  type CellRef,
  type EditableField,
} from "./sptGridNavigation"
import { caretAtEnd, caretAtStart } from "./gridKeyboard";

/**
 * SPT entry grid, rendered inline inside the SPT tab.
 *
 * Hidden until the user asks for it, so the tab reads first and entry is a
 * deliberate action.
 *
 * Navigation model. Two rhythms, matching the two things you actually do
 * while keying a log:
 *
 *   Enter / Down  "this cell is done, next one that needs a value". After the
 *                 depth column is in, that lands on the next row's first
 *                 empty blow count, skipping depths already filled.
 *   Tab           strictly left to right, then top to bottom, like a form.
 *                 Shift+Tab walks the same path back.
 *   Up            changes row, keeps the column, so a column can be keyed
 *                 top to bottom.
 *   Left / Right  move sideways between cells, for correcting something
 *                 already keyed. Right wraps to the next row from the last
 *                 column.
 *
 * Enter, Tab, Down, Up, Left and Right all work. Left/right only take over
 * at the edge of a value so a digit can still be corrected mid-number; an
 * empty cell always navigates, since it has no caret to speak of.
 *
 * Escape clears the current row. Collapsing the panel is the button's job.
 */

interface SptEntryGridProps {
  projectId: string;
  locaId: string;
  /** When set, the grid edits this record instead of creating new ones. */
  editing?: SptRecord | null;
  onSubmitted: () => Promise<void> | void;
  onCancelEdit?: () => void;
}

export function SptEntryGrid({
  projectId,
  locaId,
  editing = null,
  onSubmitted,
  onCancelEdit,
}: SptEntryGridProps) {
  // Edit mode starts with the record's own values in a single row.
  const [gridRows, setGridRows] = useState<SptRow[]>(() =>
    editing
      ? [
          {
            spt_depth: editing.spt_depth,
            blows_15: editing.blows_15,
            blows_30: editing.blows_30,
            blows_45: editing.blows_45,
          },
        ]
      : Array.from({ length: INITIAL_ROWS }, emptyRow)
  );
  const [submitting, setSubmitting] = useState(false);

  // Any row with a value in it is work that exists only in this component.
  // A pristine grid is all-empty rows, which is not worth warning about.
  const hasUnsavedRows = useMemo(
    () =>
      gridRows.some(
        (row) =>
          row.spt_depth !== null ||
          row.blows_15 !== null ||
          row.blows_30 !== null ||
          row.blows_45 !== null
      ),
    [gridRows]
  );

  useUnsavedChanges(
    "spt-grid",
    "SPT entry grid",
    hasUnsavedRows && !submitting
  );

  const [submitError, setSubmitError] = useState<string | null>(null);

  // Every editable cell carries data-spt-cell="<row>:<field>", so one
  // keydown handler can move focus anywhere without a ref per input.
  const gridRef = useRef<HTMLDivElement | null>(null);
  // Mirrors gridRows so handlers always see the live grid.
  const gridRowsRef = useRef<SptRow[]>(gridRows);
  gridRowsRef.current = gridRows;

  useEffect(() => {
    const first = gridRef.current?.querySelector<HTMLInputElement>(
      `[data-spt-cell="0:${EDITABLE_FIELDS[0]}"]`
    );
    first?.focus();
  }, []);

  function focusCell(rowIndex: number, field: EditableField) {
    const el = gridRef.current?.querySelector<HTMLInputElement>(
      `[data-spt-cell="${rowIndex}:${field}"]`
    );
    if (!el) return;
    el.focus();
    el.select();
  }

  function updateCell(index: number, field: keyof SptRow, value: number | null) {
    setGridRows((current) => {
      const next = [...current];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  }

  function addRows(count: number) {
    setGridRows((current) => [
      ...current,
      ...Array.from({ length: count }, emptyRow),
    ]);
  }

  function clearRow(rowIndex: number) {
    setGridRows((current) => {
      const next = [...current];
      next[rowIndex] = emptyRow();
      return next;
    });
    requestAnimationFrame(() => focusCell(rowIndex, EDITABLE_FIELDS[0]));
  }

  function removeRow(rowIndex: number) {
    setGridRows((current) => {
      if (current.length <= 1) return current;
      return current.filter((_, index) => index !== rowIndex);
    });
    const safeRow = Math.min(rowIndex, gridRowsRef.current.length - 2);
    if (safeRow >= 0) {
      requestAnimationFrame(() => focusCell(safeRow, EDITABLE_FIELDS[0]));
    }
  }

  /**
   * The next row's first unfilled column, then the reading-order helpers,
   * all live in sptGridNavigation so they can be tested with real data.
   * These thin wrappers just bind the live grid to them.
   */
  function here(t: CellRef | null) {
    if (t) focusCell(t.row, t.field);
    return t !== null;
  }

  function growThen(field: EditableField) {
    setGridRows((current) => compact([...current, emptyRow()]));
    const newIndex = gridRowsRef.current.length;
    requestAnimationFrame(() => focusCell(newIndex, field));
  }

  function handleGridKeyDown(
    event: React.KeyboardEvent<HTMLInputElement>,
    rowIndex: number,
    field: EditableField
  ) {
    const colIndex = EDITABLE_FIELDS.indexOf(field);

    if (event.key === "Enter" || event.key === "ArrowDown") {
      event.preventDefault();
      // Enter and Down mean "this cell is done, take me to the next one that
      // needs a value". With the depth column already keyed, that lands on
      // the next row's first empty blow count, not a depth that is filled.
      if (here(nextRowStart(gridRowsRef.current, rowIndex))) return;
      growThen(EDITABLE_FIELDS[0]);
      return;
    }

    if (event.key === "Tab") {
      event.preventDefault();
      // Tab is strictly left to right, then top to bottom, like a form.
      // Shift+Tab walks the same path back.
      const target = event.shiftKey
        ? previousInReadingOrder(gridRowsRef.current, rowIndex, colIndex)
        : nextInReadingOrder(gridRowsRef.current, rowIndex, colIndex);
      if (here(target)) return;
      growThen(EDITABLE_FIELDS[0]);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      // Up changes row but keeps the column, so a full column can be keyed
      // top to bottom and then re-read the same way.
      if (rowIndex > 0) focusCell(rowIndex - 1, field);
      return;
    }

    // Left/right stay sideways. They are the escape hatch for correcting a
    // value that was already keyed, which is why they are kept off the
    // Enter/Tab/Down path.
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      const el = event.currentTarget;
      // See gridKeyboard: every SPT cell is type="number", so selectionStart
      // is null and the old inline check was never true.
      const atStart = caretAtStart(el);
      const atEnd = caretAtEnd(el);

      if (event.key === "ArrowLeft" && atStart) {
        event.preventDefault();
        if (colIndex > 0) {
          focusCell(rowIndex, EDITABLE_FIELDS[colIndex - 1]);
        } else if (rowIndex > 0) {
          focusCell(rowIndex - 1, EDITABLE_FIELDS[EDITABLE_FIELDS.length - 1]);
        }
        return;
      }

      if (event.key === "ArrowRight" && atEnd) {
        event.preventDefault();
        if (colIndex < EDITABLE_FIELDS.length - 1) {
          focusCell(rowIndex, EDITABLE_FIELDS[colIndex + 1]);
        } else {
          // Last column: wrap to the next row rather than dead-ending.
          here(nextRowStart(gridRowsRef.current, rowIndex));
        }
        return;
      }
      return;
    }

    if (event.key === "Escape") {
      event.preventDefault();
      clearRow(rowIndex);
    }
  }

  async function submitGrid() {
    // A row counts as entered once it has a depth. Rows carrying only blow
    // counts are ignored rather than rejected, so a part-typed row cannot
    // block an otherwise valid submission.
    const populated = gridRows.filter(
      (row) => row.spt_depth !== null && row.spt_depth !== undefined
    );

    if (populated.length === 0) {
      setSubmitError("Enter an SPT depth in at least one row before submitting.");
      return;
    }

    // N-value is Below 30 + Below 45, so a depth missing either count would
    // persist an SPTN the client cannot see. Catch it here.
    const incomplete = populated.filter(
      (row) => row.blows_30 === null || row.blows_45 === null
    );
    if (incomplete.length > 0) {
      setSubmitError(
        `${incomplete.length} row(s) need the 30 cm and 45 cm blow counts before they can be submitted.`
      );
      return;
    }

    try {
      setSubmitting(true);
      setSubmitError(null);

      if (editing) {
        const target = populated[0];
        await updateSptRecord(projectId, locaId, editing.spt_depth, {
          spt_depth: target.spt_depth as number,
          blows_15: target.blows_15,
          blows_30: target.blows_30,
          blows_45: target.blows_45,
        });
      } else {
        await submitSptRecords(projectId, locaId, populated);
        // Settle the grid so a partly-keyed session reads top-down.
        setGridRows((current) =>
          compact(
            Array.from({ length: INITIAL_ROWS }, emptyRow).concat(
              current.filter((row) => !isBlank(row))
            )
          )
        );
      }

      await onSubmitted();
    } catch (err) {
      setSubmitError(
        err instanceof Error ? err.message : "Unable to submit SPT records."
      );
    } finally {
      setSubmitting(false);
    }
  }

  const openCount = gridRows.length;
  const filledCount = gridRows.filter(isFilled).length;
  const isEditMode = editing !== null;

  return (
    <div className="spt-entry-grid">
      <p className="page-sub">
        {isEditMode
          ? "Editing an existing record. Enter or Tab moves to the next empty cell · Esc clears the row."
          : `Enter or ↓ jumps to the next empty cell · Tab moves left to right · ↑ moves up a column · ←/→ move sideways to correct a value · Esc clears a row. The grid grows past ${INITIAL_ROWS} rows on its own.`}
      </p>

      {submitError && (
        <p className="page-sub field-error" style={{ marginTop: 8 }}>
          {submitError}
        </p>
      )}

      <div className="table-scroll" ref={gridRef}>
        <table className="dtable">
          <thead>
            <tr>
              <th>List No</th>
              <th>SPT Depth (m)</th>
              <th>Blows @15cm</th>
              <th>Blows @30cm</th>
              <th>Blows @45cm</th>
              <th>SPTN (Below 30 + Below 45)</th>
              <th aria-label="Row actions" />
            </tr>
          </thead>
          <tbody>
            {gridRows.map((row, index) => (
              <tr key={index}>
                {/* In edit mode this is the record's own number; in the bulk
                    grid it is the row's position, which is what the server
                    will assign once the run sits in depth order. */}
                <td className="cell-dim" data-label="List No">
                  {editing ? editing.list_no : index + 1}
                </td>
                <td>
                  <input
                    className="modal-input"
                    type="number"
                    step="0.01"
                    min="0"
                    data-spt-cell={`${index}:spt_depth`}
                    value={row.spt_depth ?? ""}
                    onKeyDown={(e) => handleGridKeyDown(e, index, "spt_depth")}
                    onChange={(e) =>
                      updateCell(
                        index,
                        "spt_depth",
                        e.target.value === "" ? null : Number(e.target.value)
                      )
                    }
                  />
                </td>
                <td>
                  <input
                    className="modal-input"
                    type="number"
                    min="0"
                    data-spt-cell={`${index}:blows_15`}
                    value={row.blows_15 ?? ""}
                    onKeyDown={(e) => handleGridKeyDown(e, index, "blows_15")}
                    onChange={(e) =>
                      updateCell(
                        index,
                        "blows_15",
                        e.target.value === "" ? null : Number(e.target.value)
                      )
                    }
                  />
                </td>
                <td>
                  <input
                    className="modal-input"
                    type="number"
                    min="0"
                    data-spt-cell={`${index}:blows_30`}
                    value={row.blows_30 ?? ""}
                    onKeyDown={(e) => handleGridKeyDown(e, index, "blows_30")}
                    onChange={(e) =>
                      updateCell(
                        index,
                        "blows_30",
                        e.target.value === "" ? null : Number(e.target.value)
                      )
                    }
                  />
                </td>
                <td>
                  <input
                    className="modal-input"
                    type="number"
                    min="0"
                    data-spt-cell={`${index}:blows_45`}
                    value={row.blows_45 ?? ""}
                    onKeyDown={(e) => handleGridKeyDown(e, index, "blows_45")}
                    onChange={(e) =>
                      updateCell(
                        index,
                        "blows_45",
                        e.target.value === "" ? null : Number(e.target.value)
                      )
                    }
                  />
                </td>
                <td className="num">{formatNumber(computeN(row))}</td>
                <td>
                  <div className="actions">
                    <button
                      type="button"
                      className="btn btn-sm btn-warn"
                      onClick={() => clearRow(index)}
                      aria-label={`Clear row ${index + 1}`}
                    >
                      Clear
                    </button>
                    {!isEditMode && gridRows.length > 1 && (
                      <button
                        type="button"
                        className="btn btn-sm btn-danger"
                        onClick={() => removeRow(index)}
                        aria-label={`Remove row ${index + 1}`}
                      >
                        Remove
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="actions spt-entry-footer">
        <span className="page-sub">
          {isEditMode
            ? "Editing 1 existing record"
            : `${openCount} row${openCount === 1 ? "" : "s"} open · ${filledCount} ready to submit`}
        </span>
        <div className="actions">
          {!isEditMode && (
            <>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => addRows(50)}
              >
                + 50 Rows
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => addRows(10)}
              >
                + 10 Rows
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => addRows(1)}
              >
                + 1 Row
              </button>
            </>
          )}
          {isEditMode && onCancelEdit && (
            <button type="button" className="btn btn-sm" onClick={onCancelEdit}>
              Cancel Edit
            </button>
          )}
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={submitGrid}
            disabled={submitting}
          >
            {submitting
              ? "Saving…"
              : isEditMode
                ? "Save Changes"
                : "Submit for Approval"}
          </button>
        </div>
      </div>
    </div>
  );
}
