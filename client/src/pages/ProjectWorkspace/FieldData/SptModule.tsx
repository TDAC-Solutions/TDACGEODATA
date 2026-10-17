import { useEffect, useState } from "react";

import { AttachmentsPanel } from "../AttachmentsPanel";
import {
  getSptRecords,
  updateSptRecord,
  deleteSptRecord,
  getPendingSptRecords,
  approveSptRecord,
  rejectSptRecord,
  getAuditSampleHistory,
  type SptRecord,
  type SptPendingRecord,
  type AuditHistory,
} from "../../../api/fieldData";
import { useAuth } from "../../../auth/AuthContext";
import { SptEntryGrid } from "./SptEntryGrid";

interface SptModuleProps {
  projectId: string;
  locaId: string;
}

/** The four values a row can be edited in, held as text so a half-typed
    number survives a re-render instead of being coerced to NaN. */
interface EditDraft {
  spt_depth: string;
  blows_15: string;
  blows_30: string;
  blows_45: string;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : String(value);
}

function statusLabel(status?: string | null): string {
  if (!status) return "—";
  return status.charAt(0) + status.slice(1).toLowerCase();
}

function draftFromRecord(record: SptRecord): EditDraft {
  const asText = (value: number | null | undefined) =>
    value === null || value === undefined ? "" : String(value);

  return {
    spt_depth: asText(record.spt_depth),
    blows_15: asText(record.blows_15),
    blows_30: asText(record.blows_30),
    blows_45: asText(record.blows_45),
  };
}

function parseNumeric(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** Live N-value preview while the row is open. Mirrors the server rule
    (Below 30 + Below 45, plain sum) so the number the user sees before saving
    is the number that lands in the database. */
function computePreviewN(draft: EditDraft): number | null {
  const b30 = parseNumeric(draft.blows_30);
  const b45 = parseNumeric(draft.blows_45);
  if (b30 === null || b45 === null) return null;
  return b30 + b45;
}

export function SptModule({ projectId, locaId }: SptModuleProps) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  const [records, setRecords] = useState<SptRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [pending, setPending] = useState<SptPendingRecord[]>([]);
  const [pendingLoading, setPendingLoading] = useState(false);
  const [reviewError, setReviewError] = useState<string | null>(null);

  // Entry is hidden by default and used for NEW records only. Editing an
  // existing record happens inline in its own row, so the row the user
  // clicked is the row they edit - no jump to a grid at the top of the page
  // they may never scroll back up to see.
  const [entryOpen, setEntryOpen] = useState(false);

  const [editingDepth, setEditingDepth] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);

  // Which SPT row's attachment panel is open, if any. Keyed on sample id
  // rather than depth so it survives a depth correction.
  const [attachTarget, setAttachTarget] = useState<{
    sampleId: string;
    depth: number;
  } | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Delete confirmation lives in app state, not window.confirm, so the
  // decision happens inside the app instead of a browser chrome dialog.
  const [deleteTarget, setDeleteTarget] = useState<SptRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Changes-pending-approval dialog. Fed by the same audit history the Audit
  // System panel reads, so a reviewer never has to leave the SPT tab to see
  // what an edit actually changed.
  const [diffTarget, setDiffTarget] = useState<SptPendingRecord | null>(null);
  const [diffData, setDiffData] = useState<AuditHistory | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  async function loadRecords() {
    try {
      setLoading(true);
      setError(null);
      const data = await getSptRecords(projectId, locaId);
      setRecords(data);
    } catch (err) {
      console.error("Failed to load SPT records:", err);
      setError(err instanceof Error ? err.message : "Unable to load SPT data.");
    } finally {
      setLoading(false);
    }
  }

  async function loadPending() {
    if (!isAdmin) return;
    try {
      setPendingLoading(true);
      const data = await getPendingSptRecords(projectId, locaId);
      setPending(data);
    } catch (err) {
      console.error("Failed to load pending SPT records:", err);
    } finally {
      setPendingLoading(false);
    }
  }

  // Reload when the location or the role changes. Keyed on all three so a
  // user promoted to admin picks up the pending list, and a location switch
  // discards the previous location's records.
  useEffect(() => {
    loadRecords();
    loadPending();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, locaId, isAdmin]);

  // ------------------------------------------------------------------
  // Inline row editing
  // ------------------------------------------------------------------
  function startEdit(record: SptRecord) {
    setEditingDepth(record.spt_depth);
    setEditDraft(draftFromRecord(record));
    setEditError(null);
  }

  function cancelEdit() {
    setEditingDepth(null);
    setEditDraft(null);
    setEditError(null);
  }

  function setDraftField(field: keyof EditDraft, value: string) {
    setEditDraft((current) => (current ? { ...current, [field]: value } : current));
  }

  async function saveEdit(originalDepth: number) {
    if (!editDraft) return;

    const depth = parseNumeric(editDraft.spt_depth);
    if (depth === null) {
      setEditError("SPT depth is required.");
      return;
    }

    setSavingEdit(true);
    setEditError(null);
    try {
      await updateSptRecord(projectId, locaId, originalDepth, {
        spt_depth: depth,
        blows_15: parseNumeric(editDraft.blows_15),
        blows_30: parseNumeric(editDraft.blows_30),
        blows_45: parseNumeric(editDraft.blows_45),
      });
      // The server puts the record back to PENDING on every edit, so both
      // lists are reloaded to pick up the fresh status and the admin queue.
      await loadRecords();
      await loadPending();
      setEditingDepth(null);
      setEditDraft(null);
    } catch (err) {
      console.error("Failed to update SPT record:", err);
      setEditError(err instanceof Error ? err.message : "Unable to save changes.");
    } finally {
      setSavingEdit(false);
    }
  }

  // ------------------------------------------------------------------
  // Delete
  // ------------------------------------------------------------------
  function requestDelete(record: SptRecord) {
    setDeleteTarget(record);
    setDeleteError(null);
  }

  function cancelDelete() {
    setDeleteTarget(null);
    setDeleteError(null);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    const depth = deleteTarget.spt_depth;
    try {
      setDeleting(true);
      setDeleteError(null);
      await deleteSptRecord(projectId, locaId, depth);
      setRecords((current) =>
        current.filter((item) => item.spt_depth !== depth)
      );
      setDeleteTarget(null);
      // Keep the admin queue in step; the deleted record may have been
      // sitting in it.
      if (isAdmin) {
        await loadPending();
      }
    } catch (err) {
      console.error("Failed to delete SPT record:", err);
      setDeleteError(
        err instanceof Error ? err.message : "Unable to delete SPT record."
      );
    } finally {
      setDeleting(false);
    }
  }

  // ------------------------------------------------------------------
  // Admin approval
  // ------------------------------------------------------------------
  async function approveRow(record: SptPendingRecord) {
    try {
      setReviewError(null);
      await approveSptRecord(projectId, locaId, record.spt_depth);
      await loadPending();
      await loadRecords();
    } catch (err) {
      console.error("Failed to approve SPT record:", err);
      setReviewError(err instanceof Error ? err.message : "Unable to approve.");
    }
  }

  async function rejectRow(record: SptPendingRecord) {
    const reason = window.prompt("Reason for rejection (optional):", "");
    try {
      setReviewError(null);
      await rejectSptRecord(projectId, locaId, record.spt_depth, reason || null);
      await loadPending();
      await loadRecords();
    } catch (err) {
      console.error("Failed to reject SPT record:", err);
      setReviewError(err instanceof Error ? err.message : "Unable to reject.");
    }
  }

  // ------------------------------------------------------------------
  // Changes preview for rows sitting in the queue because of an edit
  // ------------------------------------------------------------------
  async function openDiff(record: SptPendingRecord) {
    setDiffTarget(record);
    setDiffData(null);
    setDiffError(null);
    setDiffLoading(true);
    try {
      setDiffData(await getAuditSampleHistory(projectId, locaId, record.sample_id));
    } catch (err) {
      console.error("Failed to load sample history:", err);
      setDiffError(
        err instanceof Error ? err.message : "Unable to load the changes."
      );
    } finally {
      setDiffLoading(false);
    }
  }

  function closeDiff() {
    setDiffTarget(null);
    setDiffData(null);
    setDiffError(null);
  }

  if (loading) {
    return <p className="page-sub">Loading Field Data…</p>;
  }

  if (error) {
    return <p className="page-sub field-error">{error}</p>;
  }

  return (
    <div>
      <div className="module-toolbar">
        <h3 className="panel-subtitle">SPT</h3>
        <div className="actions">
          <button
            type="button"
            className={entryOpen ? "btn btn-sm" : "btn btn-sm btn-primary"}
            onClick={() => setEntryOpen((open) => !open)}
            aria-expanded={entryOpen}
            aria-controls="spt-entry-grid"
          >
            {entryOpen ? "Hide Entry Grid" : "Enter SPT Data"}
          </button>
        </div>
      </div>

      {entryOpen && (
        <div id="spt-entry-grid" className="spt-entry-panel">
          <SptEntryGrid
            key="entry"
            projectId={projectId}
            locaId={locaId}
            onSubmitted={async () => {
              // Reload first, then collapse. The grid has done its job once
              // the data is stored, and leaving it open above a fresh records
              // table is just clutter.
              await loadRecords();
              await loadPending();
              setEntryOpen(false);
            }}
          />
        </div>
      )}

      <h3 className="panel-subtitle" style={{ marginTop: "20px" }}>
        Submitted SPT Records
      </h3>

      {editError && <p className="page-sub field-error">{editError}</p>}

      {records.length === 0 ? (
        <div className="empty-state">
          <h3>No SPT data</h3>
          <p>No SPT records have been submitted for this location yet.</p>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="dtable spt-inline-edit">
            <thead>
              <tr>
                <th>List No</th>
                <th>SPT Depth (m)</th>
                <th>Blows @15cm</th>
                <th>Blows @30cm</th>
                <th>Blows @45cm</th>
                <th>SPT N-value</th>
                <th>Status</th>
                <th>Files</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {records.map((record) => {
                const isEditing = editingDepth === record.spt_depth;
                const previewN =
                  isEditing && editDraft ? computePreviewN(editDraft) : record.n_value;

                return (
                  <tr key={record.spt_depth}>
                    {/* Outside the editing ternary: the number is the same
                        whether or not the row is being edited. */}
                    <td className="cell-dim" data-label="List No">
                      {record.list_no}
                    </td>
                    {isEditing && editDraft ? (
                      <>
                        <td>
                          <input
                            className="modal-input spt-inline-input"
                            type="number"
                            inputMode="decimal"
                            step="0.01"
                            min="0"
                            value={editDraft.spt_depth}
                            onChange={(e) =>
                              setDraftField("spt_depth", e.target.value)
                            }
                          />
                        </td>
                        <td>
                          <input
                            className="modal-input spt-inline-input"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            value={editDraft.blows_15}
                            onChange={(e) =>
                              setDraftField("blows_15", e.target.value)
                            }
                          />
                        </td>
                        <td>
                          <input
                            className="modal-input spt-inline-input"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            value={editDraft.blows_30}
                            onChange={(e) =>
                              setDraftField("blows_30", e.target.value)
                            }
                          />
                        </td>
                        <td>
                          <input
                            className="modal-input spt-inline-input"
                            type="number"
                            inputMode="numeric"
                            min="0"
                            value={editDraft.blows_45}
                            onChange={(e) =>
                              setDraftField("blows_45", e.target.value)
                            }
                          />
                        </td>
                        <td className="num">{formatNumber(previewN)}</td>
                        <td>
                          <span className="chip chip-info">Editing…</span>
                        </td>
                        {/* Files has no inline editor, so this cell is held
                            open rather than left out: without it the Status
                            and Actions columns sit one to the left of the
                            header for as long as the row is being edited. */}
                        <td className="cell-dim" />
                        <td>
                          <div className="actions">
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={() => saveEdit(record.spt_depth)}
                              disabled={savingEdit}
                            >
                              {savingEdit ? "Saving…" : "Save"}
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={cancelEdit}
                              disabled={savingEdit}
                            >
                              Cancel
                            </button>
                          </div>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="num" data-label="SPT Depth (m)">{formatNumber(record.spt_depth)}</td>
                        <td className="num" data-label="Blows @15cm">{formatNumber(record.blows_15)}</td>
                        <td className="num" data-label="Blows @30cm">{formatNumber(record.blows_30)}</td>
                        <td className="num" data-label="Blows @45cm">{formatNumber(record.blows_45)}</td>
                        <td className="num" data-label="SPT N-value">{formatNumber(record.n_value)}</td>
                        <td data-label="Status">
                          <span className="tab-badge">
                            {statusLabel(record.status)}
                          </span>
                        </td>
                        <td data-label="Files" className="cell-dim">
                  {record.sample_id ? (
                    <button
                      type="button"
                      className="btn"
                      onClick={() =>
                        setAttachTarget({
                          sampleId: record.sample_id as string,
                          depth: record.spt_depth,
                        })
                      }
                      aria-label={`Attachments for ${record.spt_depth} m`}
                    >
                      {record.attachment_count ?? 0}
                    </button>
                  ) : (
                    <span title="No sample id for this row">
                      {record.attachment_count ?? 0}
                    </span>
                  )}
                </td>

                <td data-label="Actions">
                          <div className="actions">
                            <button
                              type="button"
                              className="btn btn-sm btn-edit"
                              onClick={() => startEdit(record)}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className="btn btn-sm btn-danger"
                              onClick={() => requestDelete(record)}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {isAdmin && (
        <>
          <h3 className="panel-subtitle" style={{ marginTop: "20px" }}>
            Pending SPT Approvals
          </h3>

          {reviewError && <p className="page-sub field-error">{reviewError}</p>}

          {pendingLoading ? (
            <p className="page-sub">Loading pending approvals…</p>
          ) : pending.length === 0 ? (
            <p className="page-sub">No SPT records awaiting approval.</p>
          ) : (
            <div className="table-scroll">
              <table className="dtable">
                <thead>
                  <tr>
                    <th>List No</th>
                    <th>Sample ID</th>
                    <th>Depth (m)</th>
                    <th>Blows @15/30/45</th>
                    <th>SPT N-value</th>
                    <th>Submitted By</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {pending.map((record) => (
                    <tr key={record.spt_depth}>
                      <td className="cell-dim" data-label="List No">{record.list_no}</td>
                      <td className="sample-id-cell" data-label="Sample ID">{record.sample_id}</td>
                      <td className="num" data-label="Depth (m)">{formatNumber(record.spt_depth)}</td>
                      <td className="num" data-label="Blows @15/30/45">
                        {formatNumber(record.blows_15)} /{" "}
                        {formatNumber(record.blows_30)} /{" "}
                        {formatNumber(record.blows_45)}
                      </td>
                      <td className="num" data-label="SPT N-value">{formatNumber(record.n_value)}</td>
                      <td data-label="Submitted By">
                        {/* The submitter stays visible, with the editor on a
                            second line: a row that was approved, quietly
                            edited and re-queued is otherwise indistinguishable
                            from a brand new submission. */}
                        <div>{record.created_by || "—"}</div>
                        {record.last_edited_by && (
                          <div className="cell-dim" style={{ marginTop: 2 }}>
                            <span className="chip chip-info">Edited</span> by{" "}
                            {record.last_edited_by}
                          </div>
                        )}
                      </td>
                      <td data-label="Actions">
                        <div className="actions">
                          {record.last_edited_by && (
                            <button
                              type="button"
                              className="btn btn-sm"
                              onClick={() => openDiff(record)}
                            >
                              View changes
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            onClick={() => approveRow(record)}
                          >
                            Approve
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => rejectRow(record)}
                          >
                            Reject
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {deleteTarget && (
        <DeleteConfirmModal
          record={deleteTarget}
          busy={deleting}
          error={deleteError}
          onCancel={cancelDelete}
          onConfirm={confirmDelete}
        />
      )}

      {diffTarget && (
        <DiffModal
          record={diffTarget}
          history={diffData}
          loading={diffLoading}
          error={diffError}
          onClose={closeDiff}
        />
      )}

      {attachTarget && (
        <AttachmentsPanel
          projectId={projectId}
          scope={{ kind: "sample", sampleId: attachTarget.sampleId }}
          onClose={() => setAttachTarget(null)}
        />
      )}
    </div>
  );
}

/* ============================================================
   DELETE CONFIRMATION DIALOG
   Replaces window.confirm so the decision stays inside the app
   and matches the rest of the UI.
   ============================================================ */

interface DeleteConfirmModalProps {
  record: SptRecord;
  busy: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

function DeleteConfirmModal({
  record,
  busy,
  error,
  onCancel,
  onConfirm,
}: DeleteConfirmModalProps) {
  // Escape and a backdrop click both close it, but not mid-delete: once the
  // request is in flight there is nothing sensible to cancel back to.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !busy) onCancel();
      }}
    >
      <div
        className="modal spt-delete-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="spt-delete-title"
      >
        <div className="panel-head">
          <h2 className="panel-title" id="spt-delete-title">
            Delete SPT record
          </h2>

          <button
            type="button"
            className="btn"
            onClick={onCancel}
            disabled={busy}
            aria-label="Close"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M2.5 2.5l7 7m0-7l-7 7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="panel-body">
          <p className="page-sub" style={{ marginTop: 0 }}>
            Delete the SPT record at <b>{formatNumber(record.spt_depth)} m</b>? This
            cannot be undone.
          </p>

          {error && <p className="page-sub field-error">{error}</p>}

          <div className="actions" style={{ justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn"
              onClick={onCancel}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={onConfirm}
              disabled={busy}
            >
              {busy ? "Deleting…" : "Delete"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   CHANGES-PENDING-APPROVAL DIALOG
   Shows the field-level diff that put a row back in the queue.
   Reads the same audit history the Audit System panel uses, so
   the two views can never disagree about what changed.
   ============================================================ */

interface DiffModalProps {
  record: SptPendingRecord;
  history: AuditHistory | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

function DiffModal({
  record,
  history,
  loading,
  error,
  onClose,
}: DiffModalProps) {
  // Read-only view, so Escape and the backdrop are always safe to honour.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Sort newest first: the reviewer's question is "what did the last edit
  // change", not "what changed at some point in the record's life".
  const changes = history
    ? [...history.changes].sort((a, b) =>
        (b.edited_at ?? "").localeCompare(a.edited_at ?? "")
      )
    : [];

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal spt-diff-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="spt-diff-title"
      >
        <div className="panel-head">
          <h2 className="panel-title" id="spt-diff-title">
            Changes pending approval
          </h2>

          <button
            type="button"
            className="btn"
            onClick={onClose}
            aria-label="Close"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 12 12"
              fill="none"
              aria-hidden="true"
            >
              <path
                d="M2.5 2.5l7 7m0-7l-7 7"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="panel-body">
          <p className="page-sub" style={{ marginTop: 0 }}>
            Sample <b>{record.sample_id}</b> · depth{" "}
            <b>{formatNumber(record.spt_depth)} m</b>
            {record.last_edited_by && (
              <>
                {" "}· last edited by <b>{record.last_edited_by}</b>
              </>
            )}
          </p>

          {loading && <p className="page-sub">Loading changes…</p>}
          {error && <p className="page-sub field-error">{error}</p>}

          {!loading && !error && changes.length === 0 && (
            <p className="page-sub">
              No field-level changes recorded for this record yet.
            </p>
          )}

          {changes.length > 0 && (
            <div className="table-scroll">
              <table className="dtable">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Old value</th>
                    <th>New value</th>
                    <th>Edited by</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((change, index) => (
                    <tr key={`${change.field}-${change.edited_at}-${index}`}>
                      <td>{change.field ?? "—"}</td>
                      <td>{String(change.old_value ?? "—")}</td>
                      <td>{String(change.new_value ?? "—")}</td>
                      <td>{change.edited_by || "—"}</td>
                      <td>
                        {change.edited_at
                          ? new Date(change.edited_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="actions" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
