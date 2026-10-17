import { useEffect, useState } from "react";
import {
  getProjectLabTests,
  getLabTest,
  type LabTestSummary,
} from "../../../../api/lab";

interface AGSMappingTabProps {
  projectId: string;
}

/**
 * AGS mapping preview.
 *
 * The server engine emits an `ags_candidate` block per test -- GRAG + GRAT
 * for grain size, LPDN for particle density, LLPL for Atterberg. This tab
 * renders the candidate blocks of the selected test's current revision so a
 * reviewer can see exactly what the release step would publish into each
 * AGS group.
 *
 * It is a preview, not a writer. Publishing stays on the QA and Approval
 * tab, which writes lab.ags_projection through the release transition.
 */
export function AGSMappingTab({ projectId }: AGSMappingTabProps) {
  const [tests, setTests] = useState<LabTestSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [candidate, setCandidate] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [standard, setStandard] = useState<string | null>(null);
  const [hasRevision, setHasRevision] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getProjectLabTests(projectId)
      .then((rows) => {
        if (cancelled) return;
        setTests(rows);
        if (rows.length > 0) setSelectedId(rows[0].test_id);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Could not load tests.");
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!selectedId) {
      setCandidate(null);
      setStandard(null);
      setHasRevision(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    getLabTest(projectId, selectedId)
      .then((detail) => {
        if (cancelled) return;
        const snapshot = detail.revision?.calculation_output_snapshot as
          | Record<string, unknown>
          | undefined;
        setHasRevision(Boolean(snapshot));
        setCandidate((snapshot?.ags as Record<string, unknown> | undefined) ?? null);
        const meta = snapshot?.meta as { standard?: string } | undefined;
        setStandard(meta?.standard ?? null);
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Could not load the test.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, selectedId]);

  const engineTests = tests.filter((t) =>
    ["PSD", "PARTICLE_DENSITY", "ATTERBERG"].includes(t.test_type)
  );

  return (
    <div>
      <div className="module-toolbar">
        <div>
          <div className="eyebrow">AGS 4.2 CANDIDATE MAPPING</div>
          <h3 className="panel-subtitle">AGS Mapping</h3>
          <p className="page-sub">
            The candidate AGS groups the release step would publish for the
            selected test's current revision. Values come from the server
            calculation engine; publishing still happens on QA and Approval,
            which writes the AGS publication record.
          </p>
        </div>

        <label>
          <span className="eyebrow">Laboratory test</span>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            disabled={loading || tests.length === 0}
          >
            <option value="">Select a test…</option>
            {tests.map((t) => (
              <option key={t.test_id} value={t.test_id}>
                {t.loca_id} · {t.samp_id} · {t.spec_ref ?? "—"} · {t.test_type}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="page-sub field-error">{error}</p>}
      {loading && <p className="page-sub">Loading…</p>}

      {!loading && !error && engineTests.length === 0 && (
        <div className="empty-state">
          <h3>No engine-backed tests yet</h3>
          <p>
            The candidate mapping is produced by the server engine for PSD,
            PARTICLE_DENSITY and ATTERBERG tests. Register one of those test
            types and save a calculated revision to see its mapping here.
          </p>
        </div>
      )}

      {!loading && !error && engineTests.length > 0 && !hasRevision && (
        <div className="empty-state">
          <h3>No calculated revision for this test</h3>
          <p>
            The selected test has no stored revision yet. Enter readings on
            the Results Entry tab and save a draft; the engine writes the AGS
            candidate blocks into the stored snapshot.
          </p>
        </div>
      )}

      {!loading && !error && candidate && (
        <div className="ags-mapping-groups">
          {standard && <p className="page-sub">Standard: {standard}</p>}

          {Object.entries(candidate).map(([key, value]) => {
            if (key === "export_note") return null;
            return (
              <div key={key} className="card" style={{ marginTop: 12 }}>
                <h3>AGS group {key}</h3>

                {/* GRAT is a row-per-point group; the rest are single
                    key/value headings. */}
                <div className="table-scroll table-scroll--no-cards">
                  <table className="dtable">
                    <thead>
                      <tr>
                        {Array.isArray(value) ? (
                          <>
                            <th>Row</th>
                            <th>Fields</th>
                          </>
                        ) : (
                          <>
                            <th>Field</th>
                            <th>Value</th>
                          </>
                        )}
                      </tr>
                    </thead>
                    <tbody>
                      {Array.isArray(value) ? (
                        (value as Record<string, unknown>[]).map((row, index) => (
                          <tr key={index}>
                            <td>{index + 1}</td>
                            <td>
                              {Object.entries(row).map(([field, fieldValue]) => (
                                <div className="re-mono" key={field}>
                                  {field} ={" "}
                                  {fieldValue === null || fieldValue === undefined
                                    ? "—"
                                    : String(fieldValue)}
                                </div>
                              ))}
                            </td>
                          </tr>
                        ))
                      ) : (
                        Object.entries(value as Record<string, unknown>).map(
                          ([field, fieldValue]) => (
                            <tr key={field}>
                              <td className="re-mono">{field}</td>
                              <td>
                                {fieldValue === null || fieldValue === undefined
                                  ? "—"
                                  : String(fieldValue)}
                              </td>
                            </tr>
                          )
                        )
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            );
          })}

          {typeof candidate.export_note === "string" && (
            <p className="paper-note">{candidate.export_note}</p>
          )}
        </div>
      )}
    </div>
  );
}
