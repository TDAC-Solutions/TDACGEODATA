import { useEffect, useState } from "react";
import {
  getAuditBoreholeEntries,
  getAuditBoreholeHistory,
  getAuditSampleEntries,
  getAuditSampleHistory,
  type AuditBoreholeEntry,
  type AuditHistory,
  type AuditSampleEntry,
} from "../../../api/fieldData";

/*
 * Admin-only audit system (Field Data -> Overview). The backend endpoints
 * require the admin role; this component is additionally only rendered for
 * admins by OverviewModule.
 */

interface FieldAuditPanelProps {
  projectId: string;
  locaId: string;
}

type AuditMode = "borehole" | "sample";

const FIELD_LABELS: Record<string, string> = {
  depth_from: "Depth From (m)",
  depth_to: "Depth To (m)",
  soil_description: "Soil Description",
  sand_clay: "Sand/Clay",
  rock_description: "Rock Description",
  recovery: "Recovery",
  rqd: "RQD",
  remark: "Remark",
  spt_depth: "SPT Depth (m)",
  blows_15: "Blows @15cm",
  blows_30: "Blows @30cm",
  blows_45: "Blows @45cm",
  n_value: "SPT N-value",
  status: "Status",
};

function label(field: string | null): string {
  if (!field) return "—";
  return FIELD_LABELS[field] ?? field;
}

function formatValue(value: unknown): string {
  return value === null || value === undefined || value === ""
    ? "—"
    : String(value);
}

function formatWhen(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function FieldAuditPanel({ projectId, locaId }: FieldAuditPanelProps) {
  const [mode, setMode] = useState<AuditMode>("borehole");

  const [boreholes, setBoreholes] = useState<AuditBoreholeEntry[]>([]);
  const [samples, setSamples] = useState<AuditSampleEntry[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);

  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [history, setHistory] = useState<AuditHistory | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setListLoading(true);
        setListError(null);
        setSelectedKey(null);
        setHistory(null);

        if (mode === "borehole") {
          const data = await getAuditBoreholeEntries(projectId, locaId);
          if (!cancelled) setBoreholes(data);
        } else {
          const data = await getAuditSampleEntries(projectId, locaId);
          if (!cancelled) setSamples(data);
        }
      } catch (err) {
        console.error("Failed to load audit entries:", err);
        if (!cancelled) {
          setListError(
            err instanceof Error ? err.message : "Unable to load audit entries."
          );
        }
      } finally {
        if (!cancelled) setListLoading(false);
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [projectId, locaId, mode]);

  async function viewHistory(key: string) {
    try {
      setSelectedKey(key);
      setHistory(null);
      setHistoryError(null);
      setHistoryLoading(true);

      const data =
        mode === "borehole"
          ? await getAuditBoreholeHistory(projectId, locaId, Number(key))
          : await getAuditSampleHistory(projectId, locaId, key);

      setHistory(data);
    } catch (err) {
      console.error("Failed to load audit history:", err);
      setHistoryError(
        err instanceof Error ? err.message : "Unable to load audit history."
      );
    } finally {
      setHistoryLoading(false);
    }
  }

  return (
    <div className="borehole-profile-panel" style={{ marginTop: "24px" }}>
      <div className="module-toolbar">
        <div>
          <h3 className="panel-subtitle">Audit System</h3>
          <p className="page-sub">
            Admin only. Select an entry to view who created it and every
            field-level change made to it.
          </p>
        </div>
      </div>

      <div className="sampling-view-tabs">
        <button
          type="button"
          className={`sampling-view-tab ${mode === "borehole" ? "active" : ""}`}
          onClick={() => setMode("borehole")}
        >
          Borehole
        </button>
        <button
          type="button"
          className={`sampling-view-tab ${mode === "sample" ? "active" : ""}`}
          onClick={() => setMode("sample")}
        >
          Sample
        </button>
      </div>

      {listLoading ? (
        <p className="page-sub">Loading entries…</p>
      ) : listError ? (
        <p className="page-sub field-error">{listError}</p>
      ) : mode === "borehole" ? (
        boreholes.length === 0 ? (
          <p className="page-sub">No borehole entries for this location.</p>
        ) : (
          <div className="table-scroll table-scroll--no-cards">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Depth From (m)</th>
                  <th>Depth To (m)</th>
                  <th>Soil Description</th>
                  <th>Sand/Clay</th>
                  <th>Created By</th>
                  <th>Audit</th>
                </tr>
              </thead>
              <tbody>
                {boreholes.map((entry) => (
                  <tr
                    key={`${entry.depth_from}-${entry.depth_to}`}
                    className={
                      selectedKey === String(entry.depth_from) ? "selected" : ""
                    }
                  >
                    <td className="num">{formatValue(entry.depth_from)}</td>
                    <td className="num">{formatValue(entry.depth_to)}</td>
                    <td>{formatValue(entry.soil_description)}</td>
                    <td>{formatValue(entry.sand_clay)}</td>
                    <td className="cell-dim">{formatValue(entry.created_by)}</td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => viewHistory(String(entry.depth_from))}
                      >
                        View Audit History
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : samples.length === 0 ? (
        <p className="page-sub">No samples for this location.</p>
      ) : (
        <div className="table-scroll table-scroll--no-cards">
          <table className="dtable">
            <thead>
              <tr>
                <th>Sample ID</th>
                <th>Source</th>
                <th>Depth From (m)</th>
                <th>Status</th>
                <th>Created By</th>
                <th>Audit</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((entry) => (
                <tr
                  key={entry.sample_id}
                  className={selectedKey === entry.sample_id ? "selected" : ""}
                >
                  <td className="sample-id-cell">{entry.sample_id}</td>
                  <td>{entry.source === "SPT" ? "SPT / Soil" : entry.source === "ROCK" ? "Rock" : "Coring"}</td>
                  <td className="num">{formatValue(entry.depth_from)}</td>
                  <td>{formatValue(entry.status)}</td>
                  <td className="cell-dim">{formatValue(entry.created_by)}</td>
                  <td>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => viewHistory(entry.sample_id)}
                    >
                      View Audit History
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {historyLoading && <p className="page-sub">Loading audit history…</p>}

      {historyError && <p className="page-sub field-error">{historyError}</p>}

      {history && (
        <div style={{ marginTop: "16px" }}>
          <h3 className="panel-subtitle">
            {mode === "sample" && history.sample_id
              ? `Sample ${history.sample_id}`
              : `Borehole entry at ${formatValue(history.entry.depth_from)} m`}
          </h3>

          <div className="table-scroll table-scroll--no-cards">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Created By</th>
                  <th>Created At</th>
                  <th>Last Edited By</th>
                  <th>Last Edited At</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>{formatValue(history.created_by)}</td>
                  <td>{formatWhen(history.created_at)}</td>
                  <td>{formatValue(history.last_edited_by)}</td>
                  <td>{formatWhen(history.last_edited_at)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <h4 className="eyebrow" style={{ marginTop: "16px" }}>
            {mode === "sample" ? "SAMPLE DETAILS" : "ENTRY DETAILS"}
          </h4>
          <div className="table-scroll table-scroll--no-cards">
            <table className="dtable">
              <tbody>
                {Object.entries(history.entry).map(([field, value]) => (
                  <tr key={field}>
                    <th>{label(field)}</th>
                    <td>{formatValue(value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <h4 className="eyebrow" style={{ marginTop: "16px" }}>
            EDIT HISTORY
          </h4>
          {history.changes.length === 0 ? (
            <p className="page-sub">No edits recorded for this entry.</p>
          ) : (
            <div className="table-scroll table-scroll--no-cards">
              <table className="dtable">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>Old Value</th>
                    <th>New Value</th>
                    <th>Edited By</th>
                    <th>Date / Time</th>
                  </tr>
                </thead>
                <tbody>
                  {history.changes.map((change, index) => (
                    <tr key={`${change.field}-${change.edited_at}-${index}`}>
                      <td>{label(change.field)}</td>
                      <td>{formatValue(change.old_value)}</td>
                      <td>{formatValue(change.new_value)}</td>
                      <td>{formatValue(change.edited_by)}</td>
                      <td>{formatWhen(change.edited_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {history.events.length > 0 && (
            <>
              <h4 className="eyebrow" style={{ marginTop: "16px" }}>
                WORKFLOW EVENTS
              </h4>
              <div className="table-scroll table-scroll--no-cards">
                <table className="dtable">
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>By</th>
                      <th>Date / Time</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.events.map((event, index) => (
                      <tr key={`${event.action}-${event.at}-${index}`}>
                        <td>{event.action}</td>
                        <td>{formatValue(event.by)}</td>
                        <td>{formatWhen(event.at)}</td>
                        <td>{formatValue(event.detail)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}
