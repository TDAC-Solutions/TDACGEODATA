import { useEffect, useState } from "react";
import {
  getBoreholeRecords,
  createBoreholeRecord,
  updateBoreholeRecord,
  deleteBoreholeRecord,
  type BoreholeRecord,
  type BoreholeUpdate,
} from "../../../api/fieldData";

interface BoreholeModuleProps {
  projectId: string;
  locaId: string;
}

function formatNumber(value: number | null): string {
  return value === null || value === undefined ? "—" : String(value);
}

/** depth_from is null until it is typed, not 0. 0 is a real depth -- the top
 *  of every borehole -- so a 0 default both looked like entered data and
 *  silently created a stratum at 0.00 m if the user only filled in the
 *  description. The draft is converted to BoreholeCreate on submit. */
interface BoreholeDraft {
  depth_from: string;
  depth_to: string;
  soil_description: string | null;
  sand_clay: string | null;
}

const EMPTY_DRAFT: BoreholeDraft = {
  depth_from: "",
  depth_to: "",
  soil_description: null,
  sand_clay: null,
};

export function BoreholeModule({
  projectId,
  locaId,
}: BoreholeModuleProps) {
  const [records, setRecords] = useState<BoreholeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [editingKey, setEditingKey] = useState<number | null>(null);
  const [draft, setDraft] = useState<BoreholeUpdate | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [newRecord, setNewRecord] =
    useState<BoreholeDraft>(EMPTY_DRAFT);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] =
    useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const data = await getBoreholeRecords(
          projectId,
          locaId
        );

        if (!cancelled) {
          setRecords(
            [...data].sort(
              (a, b) => a.depth_from - b.depth_from
            )
          );
        }
      } catch (err) {
        console.error(
          "Failed to load borehole records:",
          err
        );

        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load borehole/drilling data."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [projectId, locaId]);

  function startAdd() {
    setNewRecord(EMPTY_DRAFT);
    setCreateError(null);
    setAdding(true);
  }

  function cancelAdd() {
    setAdding(false);
    setCreateError(null);
  }

  async function saveNewRecord() {
    const fromRaw = newRecord.depth_from.trim();
    const toRaw = newRecord.depth_to.trim();

    if (fromRaw === "") {
      setCreateError("Depth From is required.");
      return;
    }
    const depthFrom = Number(fromRaw);
    if (!Number.isFinite(depthFrom) || depthFrom < 0) {
      setCreateError("Depth From must be zero or greater.");
      return;
    }
    let depthTo: number | null = null;
    if (toRaw !== "") {
      depthTo = Number(toRaw);
      if (!Number.isFinite(depthTo)) {
        setCreateError("Depth To must be a number.");
        return;
      }
      // Same rule the schema now enforces server-side, checked here so the
      // user is told before the round trip.
      if (depthTo <= depthFrom) {
        setCreateError("Depth To must be greater than Depth From.");
        return;
      }
    }

    try {
      setCreating(true);
      setCreateError(null);

      const created = await createBoreholeRecord(projectId, locaId, {
        depth_from: depthFrom,
        depth_to: depthTo,
        soil_description: newRecord.soil_description,
        sand_clay: newRecord.sand_clay,
      });

      setRecords((current) =>
        [...current, created].sort(
          (a, b) => a.depth_from - b.depth_from
        )
      );

      setAdding(false);
      setNewRecord(EMPTY_DRAFT);
    } catch (err) {
      console.error(
        "Failed to create borehole record:",
        err
      );

      setCreateError(
        err instanceof Error
          ? err.message
          : "Unable to create record."
      );
    } finally {
      setCreating(false);
    }
  }

  function startEdit(record: BoreholeRecord) {
    setEditingKey(record.depth_from);

    setDraft({
      depth_from: record.depth_from,
      depth_to: record.depth_to,
      soil_description: record.soil_description,
      sand_clay: record.sand_clay,
    });

    setSaveError(null);
  }

  function cancelEdit() {
    setEditingKey(null);
    setDraft(null);
    setSaveError(null);
  }

  async function saveEdit(originalDepthFrom: number) {
    if (!draft) {
      return;
    }

    try {
      setSaving(true);
      setSaveError(null);

      const updated = await updateBoreholeRecord(
        projectId,
        locaId,
        originalDepthFrom,
        draft
      );

      setRecords((current) =>
        current
          .map((record) =>
            record.depth_from === originalDepthFrom
              ? { ...record, ...updated }
              : record
          )
          .sort(
            (a, b) => a.depth_from - b.depth_from
          )
      );

      setEditingKey(null);
      setDraft(null);
    } catch (err) {
      console.error(
        "Failed to update borehole record:",
        err
      );

      setSaveError(
        err instanceof Error
          ? err.message
          : "Unable to save changes."
      );
    } finally {
      setSaving(false);
    }
  }

  async function deleteRecord(record: BoreholeRecord) {
    const confirmed = window.confirm(
      `Delete the borehole record at ${record.depth_from} m?`
    );

    if (!confirmed) {
      return;
    }

    try {
      setSaveError(null);

      await deleteBoreholeRecord(
        projectId,
        locaId,
        record.depth_from
      );

      setRecords((current) =>
        current.filter(
          (item) =>
            item.depth_from !== record.depth_from
        )
      );
    } catch (err) {
      console.error(
        "Failed to delete borehole record:",
        err
      );

      setSaveError(
        err instanceof Error
          ? err.message
          : "Unable to delete borehole record."
      );
    }
  }

  if (loading) {
    return (
      <p className="page-sub">
        Loading Field Data…
      </p>
    );
  }

  if (error) {
    return (
      <p className="page-sub field-error">
        {error}
      </p>
    );
  }

  return (
    <div>
      {/* HEADER */}
      <div className="module-toolbar">
        <h3 className="panel-subtitle">
          Borehole / Drilling
        </h3>

        {!adding && (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={startAdd}
          >
            + Add Record
          </button>
        )}
      </div>

      {/* ADD RECORD */}
      {adding && (
        <div className="add-record-form">
          <div className="form-grid">
            <label>
              <span className="eyebrow">
                DEPTH FROM (m) *
              </span>

              <input
                className="modal-input"
                type="number"
                step="0.01"
                value={newRecord.depth_from}
                onChange={(event) =>
                  setNewRecord({
                    ...newRecord,
                    depth_from: event.target.value,
                  })
                }
              />
            </label>

            <label>
              <span className="eyebrow">
                DEPTH TO (m)
              </span>

              <input
                className="modal-input"
                type="number"
                step="0.01"
                value={newRecord.depth_to}
                onChange={(event) =>
                  setNewRecord({
                    ...newRecord,
                    depth_to: event.target.value,
                  })
                }
              />
            </label>

            <label>
              <span className="eyebrow">
                SOIL DESCRIPTION
              </span>

              <input
                className="modal-input"
                type="text"
                value={
                  newRecord.soil_description ?? ""
                }
                onChange={(event) =>
                  setNewRecord({
                    ...newRecord,
                    soil_description:
                      event.target.value,
                  })
                }
              />
            </label>

            <label>
              <span className="eyebrow">
                SAND/CLAY
              </span>

              <input
                className="modal-input"
                type="text"
                value={newRecord.sand_clay ?? ""}
                onChange={(event) =>
                  setNewRecord({
                    ...newRecord,
                    sand_clay:
                      event.target.value,
                  })
                }
              />
            </label>
          </div>

          {createError && (
            <p className="page-sub field-error">
              {createError}
            </p>
          )}

          <div className="actions">
            <button
              type="button"
              className="btn"
              onClick={cancelAdd}
              disabled={creating}
            >
              Cancel
            </button>

            <button
              type="button"
              className="btn btn-primary"
              onClick={saveNewRecord}
              disabled={creating}
            >
              {creating
                ? "Adding…"
                : "Add Record"}
            </button>
          </div>
        </div>
      )}

      {/* RECORDS */}
      {records.length === 0 ? (
        <div className="empty-state">
          <h3>
            No borehole/drilling data
          </h3>

          <p>
            No borehole/drilling data
            available for this location.
          </p>
        </div>
      ) : (
        <>
          <div className="borehole-records-scroll">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Depth From (m)</th>
                  <th>Depth To (m)</th>
                  <th>Soil Description</th>
                  <th>Sand/Clay</th>
                  <th>Average N Value</th>
                  <th>Created By</th>
                  <th>Actions</th>
                </tr>
              </thead>

              <tbody>
                {records.map((record) => {
                  const isEditing =
                    editingKey ===
                    record.depth_from;

                  return (
                    <tr
                      key={`${record.depth_from}-${record.depth_to}`}
                    >
                      {isEditing && draft ? (
                        <>
                          <td data-label="Depth From (m)">
                            <input
                              className="modal-input"
                              type="number"
                              step="0.01"
                              value={
                                draft.depth_from
                              }
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  depth_from:
                                    Number(
                                      event
                                        .target
                                        .value
                                    ),
                                })
                              }
                            />
                          </td>

                          <td data-label="Depth To (m)">
                            <input
                              className="modal-input"
                              type="number"
                              step="0.01"
                              value={
                                draft.depth_to ??
                                ""
                              }
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  depth_to:
                                    event.target
                                      .value === ""
                                      ? null
                                      : Number(
                                          event
                                            .target
                                            .value
                                        ),
                                })
                              }
                            />
                          </td>

                          <td data-label="Soil Description">
                            <input
                              className="modal-input"
                              type="text"
                              value={
                                draft.soil_description ??
                                ""
                              }
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  soil_description:
                                    event.target
                                      .value,
                                })
                              }
                            />
                          </td>

                          <td data-label="Sand/Clay">
                            <input
                              className="modal-input"
                              type="text"
                              value={
                                draft.sand_clay ??
                                ""
                              }
                              onChange={(event) =>
                                setDraft({
                                  ...draft,
                                  sand_clay:
                                    event.target
                                      .value,
                                })
                              }
                            />
                          </td>

                          <td className="num cell-dim" data-label="Average N Value">
                            {formatNumber(
                              record.avg_n_value
                            )}
                          </td>
                          <td className="cell-dim" data-label="Created By">
                            {record.created_by || "—"}
                          </td>

                          <td data-label="Actions">
                            <div className="actions">
                              <button
                                type="button"
                                className="btn btn-sm btn-primary"
                                disabled={saving}
                                onClick={() =>
                                  saveEdit(
                                    record.depth_from
                                  )
                                }
                              >
                                {saving
                                  ? "Saving…"
                                  : "Save"}
                              </button>

                              <button
                                type="button"
                                className="btn btn-sm"
                                disabled={saving}
                                onClick={
                                  cancelEdit
                                }
                              >
                                Cancel
                              </button>
                            </div>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="num" data-label="Depth From (m)">
                            {formatNumber(
                              record.depth_from
                            )}
                          </td>

                          <td className="num" data-label="Depth To (m)">
                            {formatNumber(
                              record.depth_to
                            )}
                          </td>

                          <td data-label="Soil Description">
                            {record.soil_description ||
                              "—"}
                          </td>

                          <td data-label="Sand/Clay">
                            {record.sand_clay ||
                              "—"}
                          </td>

                          <td
                            className="num"
                            data-label="Average N Value"
                          >
                            {formatNumber(
                              record.avg_n_value
                            )}
                          </td>
                          <td className="cell-dim" data-label="Created By">
                            {record.created_by || "—"}
                          </td>

                          <td data-label="Actions">
                            <div className="actions">
                              <button
                                type="button"
                                className="btn btn-sm btn-edit"
                                onClick={() =>
                                  startEdit(record)
                                }
                              >
                                Edit
                              </button>

                              <button
                                type="button"
                                className="btn btn-sm btn-danger"
                                onClick={() =>
                                  deleteRecord(record)
                                }
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

            {saveError && (
              <p
                className="page-sub field-error"
                style={{
                  marginTop: "10px",
                }}
              >
                {saveError}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}