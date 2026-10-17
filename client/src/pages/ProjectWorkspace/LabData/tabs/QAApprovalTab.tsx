import {
  getLabTest,
  getProjectLabTests,
  getReviewQueue,
  reviewLabTest,
  type LabReviewAction,
  type LabReviewQueueRow,
  type LabTestDetail,
  type LabTestSummary,
} from "../../../../api/lab";
import { useEffect, useState } from "react";

export interface ReleaseGate {
  name: string;
  status: "pass" | "warn" | "pending";
  detail: string;
}

interface QAApprovalTabProps {
  projectId: string;
}

/** Database status -> the words the laboratory uses. */
const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Draft",
  CALCULATED: "Calculated",
  SUBMITTED: "Submitted for check",
  RETURNED: "Returned to preparer",
  CHECKED: "Checked",
  APPROVED: "Approved",
  PUBLISHED: "Published",
  SUPERSEDED: "Superseded",
  VOID: "Void",
};

function statusLabel(status: string) {
  return STATUS_LABEL[status] ?? status;
}

/**
 * The values the release step would publish for the selected test: only the
 * output keys the pinned method declares in its result_schema count, and the
 * missing declared keys are reported so a release can never look complete
 * when the calculation did not produce the method's outputs.
 */
function releasedValues(detail: LabTestDetail | null) {
  const snapshot = detail?.revision?.calculation_output_snapshot;
  const record =
    snapshot && typeof snapshot === "object"
      ? (snapshot as Record<string, unknown>)
      : {};
  const rawOutputs = record.outputs;
  const outputs =
    rawOutputs && typeof rawOutputs === "object"
      ? (rawOutputs as Record<string, unknown>)
      : {};
  const declared = detail?.result_outputs ?? [];

  // Released values live under the normalised "outputs" object for
  // revisions written by Results Entry, but older revisions store them as
  // flat top-level keys. The backend (_project_ags_rows) reads both, with
  // "outputs" taking priority, so this reader must match exactly -
  // otherwise the preview tells a reviewer there is nothing to release
  // and then Publish succeeds anyway.
  const readValue = (key: string): number | null => {
    const value = Object.prototype.hasOwnProperty.call(outputs, key)
      ? outputs[key]
      : record[key];

    if (typeof value !== "number" || Number.isNaN(value)) return null;

    return value;
  };

  const released: { key: string; value: number }[] = [];
  const missing: string[] = [];

  for (const key of declared) {
    const value = readValue(key);

    if (value === null) {
      missing.push(key);
    } else {
      released.push({ key, value });
    }
  }

  return { declared, released, missing };
}

function gateChip(status: ReleaseGate["status"]) {
  if (status === "pass") {
    return <span className="chip chip-ok">Pass</span>;
  }

  if (status === "warn") {
    return <span className="chip chip-warn">Warnings</span>;
  }

  return <span className="chip chip-muted">Pending</span>;
}

export function QAApprovalTab({ projectId }: QAApprovalTabProps) {
  const [queue, setQueue] = useState<LabReviewQueueRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<LabTestDetail | null>(null);
  const [tests, setTests] = useState<LabTestSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  // In-app return reason, captured as first-class data before the
  // "return" transition runs. window.prompt is suppressed on some mobile
  // WebViews, which would silently cancel the transition with no error.
  const [returnReason, setReturnReason] = useState("");
  const [confirmingReturn, setConfirmingReturn] = useState(false);

  async function reload() {
    const [queueData, testData] = await Promise.all([
      getReviewQueue(projectId),
      getProjectLabTests(projectId),
    ]);

    setQueue(queueData);
    setTests(testData);
  }

  // Selecting a row loads that test's real detail - revision, review events
  // and AGS publication records - so the panels below show database state.
  async function selectTest(testId: string) {
    if (!projectId) return;

    // A return dialog belongs to one row. Switching rows (or collapsing the
    // selected one) must drop the open dialog and its typed reason, or the
    // reason typed for the previous test would be submitted against another.
    setConfirmingReturn(false);
    setReturnReason("");

    if (selectedId === testId) {
      setSelectedId(null);
      setSelected(null);
      return;
    }

    setSelectedId(testId);

    try {
      setBusy(true);
      setNotice("");
      const detail = await getLabTest(projectId, testId);
      setSelected(detail);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  // Runs a real review transition on the selected test and refreshes the
  // queue so the row reflects its new database status.
  async function runAction(action: LabReviewAction) {
    if (!projectId || !selectedId) return;

    // A return must carry a reason: the backend stores it on the review
    // event. In-app dialog only — window.prompt is suppressed on some
    // Android WebView contexts and would silently cancel the transition.
    if (action === "return") {
      setReturnReason("");
      setConfirmingReturn(true);
      return;
    }

    await finalizeAction(action);
  }

  async function finalizeAction(action: LabReviewAction, reason?: string) {
    if (!projectId || !selectedId) return;

    try {
      setBusy(true);
      setNotice("");
      const detail = await reviewLabTest(projectId, selectedId, action, reason);
      setSelected(detail);

      const summary =
        action === "publish"
          ? `Released to AGS · status ${statusLabel(detail.status)} · ${detail.publication.length} publication record(s).`
          : `${statusLabel(detail.status)} recorded.`;

      // The transition is already committed at this point. A failure to
      // refresh the queue must not be reported as a failed action, or the
      // reviewer retries a change that actually succeeded.
      try {
        await reload();
        setNotice(summary);
      } catch (reloadError) {
        console.error("Queue refresh failed after a committed transition:", reloadError);
        setNotice(
          `${summary} The queue could not be refreshed — reload the page to see the current state.`
        );
      }
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setBusy(false);
      setConfirmingReturn(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const [queueData, testData] = await Promise.all([
          getReviewQueue(projectId),
          getProjectLabTests(projectId),
        ]);

        if (!cancelled) {
          setQueue(queueData);
          setTests(testData);
        }
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof Error ? err.message : "Failed to load review queue"
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
  }, [projectId]);

  // Every gate below is counted from real rows: the queue comes from
  // lab.test / lab.test_revision / lab.validation_issue, and the project
  // totals come from the project's laboratory test list.
  const submitted = queue.filter((row) => row.status === "SUBMITTED");
  const checked = queue.filter((row) => row.status === "CHECKED");
  const awaitingRelease = queue.filter((row) => row.status === "APPROVED");
  const missingRevision = queue.filter((row) => !row.has_revision);
  const totalBlockers = queue.reduce((sum, row) => sum + row.blockers, 0);
  const totalWarnings = queue.reduce((sum, row) => sum + row.warnings, 0);

  const publishedCount = tests.filter(
    (test) => test.status === "PUBLISHED"
  ).length;
  const approvedCount = tests.filter(
    (test) => test.status === "APPROVED"
  ).length;

  const gates: ReleaseGate[] = [
    {
      name: "Revision stored",
      status:
        queue.length === 0
          ? "pending"
          : missingRevision.length
          ? "warn"
          : "pass",
      detail:
        queue.length === 0
          ? "No result is in the review queue"
          : `${queue.length - missingRevision.length}/${queue.length} queued test(s) have a stored revision`,
    },
    {
      name: "Method pinned on revision",
      status:
        queue.length === 0
          ? "pending"
          : queue.every((row) => row.method_code) && missingRevision.length === 0
          ? "pass"
          : "warn",
      detail:
        queue.length === 0
          ? "No result is in the review queue"
          : Array.from(
              new Set(queue.map((row) => row.method_code ?? "no method"))
            ).join(", "),
    },
    {
      name: "Blocking issues",
      status:
        totalBlockers > 0 ? "warn" : queue.length ? "pass" : "pending",
      detail: queue.length
        ? `${totalBlockers} open blocker(s), ${totalWarnings} open warning(s)`
        : "No result is in the review queue",
    },
    {
      name: "Independent check",
      status:
        queue.length === 0
          ? "pending"
          : submitted.length > 0
          ? "warn"
          : "pass",
      detail:
        queue.length === 0
          ? "Awaiting submitted results"
          : submitted.length > 0
          ? `${submitted.length} test(s) still awaiting a check, ${checked.length} checked`
          : `All ${checked.length} checked test(s) have a checker`,
    },
    {
      name: "Approval",
      status:
        approvedCount === 0 && awaitingRelease.length === 0
          ? "pending"
          : awaitingRelease.length > 0
          ? "warn"
          : "pass",
      detail:
        approvedCount === 0
          ? "No test is approved yet"
          : `${awaitingRelease.length} approved test(s) not released yet`,
    },
    {
      name: "AGS release",
      status:
        publishedCount > 0
          ? "pass"
          : awaitingRelease.length > 0
          ? "warn"
          : "pending",
      detail: `${publishedCount} published test(s) of ${tests.length} in this project`,
    },
  ];

  const released = releasedValues(selected);

  return (
    <div>
      <div className="module-toolbar">
        <div>
          <div className="eyebrow">CONTROLLED RELEASE</div>
          <h3 className="panel-subtitle">QA and Approval</h3>
        </div>

        <div className="actions">
          <button
            type="button"
            className="btn btn-sm"
            disabled={
              busy ||
              !selected ||
              !["SUBMITTED", "CHECKED"].includes(selected.status)
            }
            onClick={() => runAction("return")}
          >
            Return with comments
          </button>
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy || !selected || selected.status !== "SUBMITTED"}
            onClick={() => runAction("check")}
          >
            Mark checked
          </button>
          {/* Approve records the approval decision only. */}
          <button
            type="button"
            className="btn btn-sm"
            disabled={busy || !selected || selected.status !== "CHECKED"}
            onClick={() => runAction("approve")}
          >
            Approve
          </button>
          {/* Publish is the release step: it writes the approved values to the
              AGS publication record and only then becomes PUBLISHED. */}
          <button
            type="button"
            className="btn btn-sm btn-primary"
            disabled={busy || !selected || selected.status !== "APPROVED"}
            onClick={() => runAction("publish")}
          >
            Publish to AGS
          </button>
        </div>
      </div>

      <div className="card">
        <h3>Result review and release queue</h3>

        <p className="page-sub">
          {tests.length} laboratory test(s) in this project · {approvedCount}{" "}
          approved but not released · {publishedCount} published.
        </p>

        {loading ? (
          <div className="empty-state">
            <h3>Loading review queue...</h3>
          </div>
        ) : error ? (
          <div className="empty-state">
            <h3>Could not load review queue</h3>
            <p>{error}</p>
          </div>
        ) : queue.length === 0 ? (
          <div className="empty-state">
            <h3>No results awaiting review</h3>
            <p>
              Submitted results appear here once tests are submitted for
              independent review. Approved results stay here until they are
              published to AGS.
            </p>
          </div>
        ) : (
          <div className="table-scroll table-scroll--no-cards">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Test</th>
                  <th>Sample / specimen</th>
                  <th>Method</th>
                  <th>Revision</th>
                  <th>Prepared by</th>
                  <th>Validation</th>
                  <th>Status</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {queue.map((item) => (
                  <tr
                    key={item.test_id}
                    style={
                      selectedId === item.test_id
                        ? { background: "var(--accent-soft, #e7f5f3)" }
                        : undefined
                    }
                  >
                    <td>{item.test_type}</td>
                    <td>
                      {item.sample_id}
                      {item.spec_ref ? ` · ${item.spec_ref}` : ""}
                      <div className="cell-dim">{item.loca_id}</div>
                    </td>
                    <td>
                      {item.method_code ?? "—"}
                      {item.method_version ? ` · v${item.method_version}` : ""}
                    </td>
                    <td>
                      {item.has_revision
                        ? `rev ${item.current_revision}`
                        : "no revision"}
                    </td>
                    <td>{item.prepared_by}</td>
                    <td>
                      {item.blockers > 0 ? (
                        <span className="chip chip-err">
                          {item.blockers} blockers
                        </span>
                      ) : item.warnings > 0 ? (
                        <span className="chip chip-warn">
                          {item.warnings} warnings
                        </span>
                      ) : (
                        <span className="chip chip-ok">Clean</span>
                      )}
                    </td>
                    <td>
                      <span className="chip chip-info">
                        {statusLabel(item.status)}
                      </span>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => selectTest(item.test_id)}
                      >
                        {selectedId === item.test_id ? "Selected" : "Select"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {notice && (
        <div
          className="card"
          style={{ marginTop: "12px", padding: "10px 14px" }}
        >
          {notice}
        </div>
      )}

      {confirmingReturn && selected && (
        <div className="card" style={{ marginTop: "12px", padding: "10px 14px" }}>
          <h3>Return for revision</h3>
          <p className="page-sub">
            Return {selected.test_id.slice(0, 8)} · {selected.test_type} to the
            preparer with comments. The reason is stored on the review event.
          </p>
          <textarea
            className="modal-input"
            style={{ width: "100%", resize: "vertical" }}
            rows={3}
            placeholder="Reason for returning (required)"
            value={returnReason}
            onChange={(event) => setReturnReason(event.target.value)}
            autoFocus
          />
          <div className="actions" style={{ marginTop: 8, justifyContent: "flex-end" }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setConfirmingReturn(false);
                setReturnReason("");
              }}
              disabled={busy}
            >
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => {
                const trimmed = returnReason.trim();
                if (trimmed === "") {
                  setNotice("A reason is required to return a test.");
                  return;
                }
                void finalizeAction("return", trimmed);
              }}
              disabled={busy || returnReason.trim() === ""}
            >
              Confirm return
            </button>
          </div>
        </div>
      )}

      <div className="card" style={{ marginTop: "12px" }}>
        <h3>Release gates</h3>

        <div className="table-scroll table-scroll--no-cards">
          <table className="dtable">
            <tbody>
              {gates.map((gate) => (
                <tr key={gate.name}>
                  <td>{gate.name}</td>
                  <td>{gate.detail}</td>
                  <td>{gateChip(gate.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card" style={{ marginTop: "12px" }}>
        <h3>Review history</h3>

        {!selected ? (
          <div className="empty-state">
            <h3>No test selected</h3>
            <p>
              Select a result from the queue to read its real review history
              from lab.review_event.
            </p>
          </div>
        ) : selected.review_events.length === 0 ? (
          <div className="empty-state">
            <h3>No review event recorded</h3>
            <p>
              This test has no entry in lab.review_event yet, so no status change
              has been recorded for it.
            </p>
          </div>
        ) : (
          <div className="table-scroll table-scroll--no-cards">
            <table className="dtable">
              <thead>
                <tr>
                  <th>Event</th>
                  <th>Transition</th>
                  <th>Actor</th>
                  <th>Role</th>
                  <th>Reason</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {selected.review_events.map((event, index) => (
                  <tr key={`${event.event_type}-${index}`}>
                    <td>{event.event_type}</td>
                    <td>
                      {event.from_status ?? "—"} → {event.to_status}
                    </td>
                    <td>{event.actor}</td>
                    <td>{event.actor_role}</td>
                    <td>{event.reason ?? "—"}</td>
                    <td>{new Date(event.event_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: "12px" }}>
        <h3>Publication preview</h3>

        {!selected ? (
          <div className="empty-state">
            <h3>Nothing selected to publish</h3>
            <p>
              Select a result from the queue to preview what the release step
              would write to the AGS publication record.
            </p>
          </div>
        ) : (
          <>
            <p className="page-sub">
              {selected.test_id.slice(0, 8)} · {selected.test_type} ·{" "}
              {statusLabel(selected.status)} · revision{" "}
              {selected.current_revision}
              {selected.method
                ? ` · ${selected.method.method_code} (${selected.method.calculation_package} ${selected.method.calculation_package_version})`
                : ""}
            </p>

            <div className="table-scroll table-scroll--no-cards">
              <table className="dtable">
                <tbody>
                  <tr>
                    <td>AGS groups of the pinned method</td>
                    <td>
                      {(selected.ags_groups ?? []).join(" + ") || "not mapped"}
                    </td>
                  </tr>
                  <tr>
                    <td>Released values in this revision</td>
                    <td>
                      {released.released.length === 0
                        ? "none"
                        : released.released
                            .map((item) => `${item.key} = ${item.value}`)
                            .join(", ")}
                    </td>
                  </tr>
                  <tr>
                    <td>Declared but not calculated yet</td>
                    <td>
                      {released.missing.length === 0
                        ? "none"
                        : released.missing.join(", ")}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>

            {selected.publication.length === 0 ? (
              <p className="paper-note">
                Not published. The release step writes one lab.ags_projection
                record per AGS group above and only then does the test become
                PUBLISHED.
              </p>
            ) : (
              <div className="table-scroll table-scroll--no-cards">
                <table className="dtable">
                  <thead>
                    <tr>
                      <th>AGS group</th>
                      <th>Rows</th>
                      <th>Record hash</th>
                      <th>Status</th>
                      <th>Published by</th>
                      <th>Published at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {selected.publication.map((record) => (
                      <tr key={record.ags_group}>
                        <td>{record.ags_group}</td>
                        <td>{record.projected_row_count}</td>
                        <td className="re-mono">
                          {record.projected_row_hash.slice(0, 16)}…
                        </td>
                        <td>{record.projection_status}</td>
                        <td>{record.projected_by ?? "—"}</td>
                        <td>
                          {record.projected_at
                            ? new Date(record.projected_at).toLocaleString()
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
