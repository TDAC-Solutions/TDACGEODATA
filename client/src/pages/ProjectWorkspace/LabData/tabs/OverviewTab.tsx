import { useEffect, useState } from "react";
import { getProjectLabTests } from "../../../../api/lab";

interface OverviewTabProps {
  projectId: string;
  onAddTest: () => void;
  onOpenResults: (testId: string) => void;
}

interface LabTest {
  test_id: string;
  loca_id: string;
  samp_id: string;
  samp_top: number | null;
  samp_base: number | null;
  spec_ref: string;
  test_type: string;
  laboratory: string;
  technician: string | null;
  test_started_at: string | null;
  test_completed_at: string | null;
  status: string;
  current_revision: number;
  created_at: string;
}

export function OverviewTab({
  projectId,
  onAddTest,
  onOpenResults,
}: OverviewTabProps) {
  const [tests, setTests] = useState<LabTest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadTests() {
    try {
      setLoading(true);
      setError("");

      const data = await getProjectLabTests(projectId);
      setTests(data);
    } catch (err) {
      console.error(err);
      setError("Failed to load laboratory tests.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTests();
  }, [projectId]);

  const totalTests = tests.length;
  const pendingTests = tests.filter(
    (test) =>
      test.status === "DRAFT" ||
      test.status === "SUBMITTED" ||
      test.status === "RETURNED"
  ).length;
  const inProgressTests = tests.filter(
    (test) =>
      test.status === "CALCULATED" ||
      test.status === "CHECKED"
  ).length;
  const completedTests = tests.filter(
    (test) =>
      test.status === "APPROVED" ||
      test.status === "PUBLISHED"
  ).length;

  return (
    <div className="lab-overview">
      <div className="lab-overview-header">
        <div>
          <h3>Laboratory Data</h3>
          <p className="page-sub">
            Laboratory testing overview and progress.
          </p>
        </div>

        <div className="lab-overview-actions">
          <button
            type="button"
            className="lab-overview-refresh-button"
            onClick={loadTests}
          >
            Refresh
          </button>

          <button
            type="button"
            className="lab-overview-add-button"
            onClick={onAddTest}
          >
            Add Test
          </button>
        </div>
      </div>

      <div className="lab-overview-summary">
        <div className="card">
          <div className="lab-summary-label">Total Tests</div>
          <div className="lab-summary-value">
            {totalTests}
          </div>
        </div>

        <div className="card">
          <div className="lab-summary-label">Pending</div>
          <div className="lab-summary-value">
            {pendingTests}
          </div>
        </div>

        <div className="card">
          <div className="lab-summary-label">In Progress</div>
          <div className="lab-summary-value">
            {inProgressTests}
          </div>
        </div>

        <div className="card">
          <div className="lab-summary-label">Completed</div>
          <div className="lab-summary-value">
            {completedTests}
          </div>
        </div>
      </div>

      <div className="lab-overview-grid">
        <div className="card">
          <h4>Work Queue</h4>

          {loading && (
            <p className="page-sub">
              Loading laboratory tests...
            </p>
          )}

          {error && (
            <p className="page-sub">
              {error}
            </p>
          )}
            {!loading && !error && tests.length === 0 && (
            <p className="page-sub">
                No laboratory tests registered yet.
            </p>
            )}

            {!loading && !error && tests.length > 0 && (
            <div className="lab-work-table-wrap">
                <table className="lab-work-table">
                <thead>
                    <tr>
                    <th>Sample / specimen</th>
                    <th>Depth</th>
                    <th>Test</th>
                    <th>Due</th>
                    <th>Status</th>
                    <th>Issue</th>
                    <th></th>
                    </tr>
                </thead>

                <tbody>
                    {tests.map((test) => (
                    <tr key={test.test_id}>
                        <td>
                        <div className="lab-sample-primary">
                            {test.samp_id} / {test.spec_ref}
                        </div>

                        <div className="lab-sample-secondary">
                            {test.loca_id}
                        </div>
                        </td>

                        <td>
                        {test.samp_top !== null
                            ? `${test.samp_top.toFixed(2)}–${
                                test.samp_base !== null
                                ? test.samp_base.toFixed(2)
                                : "—"
                            } m`
                            : "—"}
                        </td>

                        <td>
                        {test.test_type === "PSD"
                            ? "PSD sieve + hydrometer"
                            : test.test_type.replace(/_/g, " ")}
                        </td>

                        <td>—</td>

                        <td>
                        <span
                            className={`lab-status lab-status-${test.status.toLowerCase()}`}
                        >
                            {test.status === "CHECKED"
                            ? "For check"
                            : test.status === "CALCULATED"
                                ? "In progress"
                                : test.status === "PUBLISHED"
                                ? "Approved"
                                : test.status}
                        </span>
                        </td>

                        <td>—</td>

                        <td>
                          <button
                            type="button"
                            className="lab-work-action"
                            onClick={() => onOpenResults(test.test_id)}
                          >
                            {test.status === "SUBMITTED" ||
                            test.status === "CHECKED"
                              ? "Review"
                              : test.status === "APPROVED" ||
                                  test.status === "PUBLISHED"
                                ? "View"
                                : "Open"}
                          </button>
                        </td>
                    </tr>
                    ))}
                </tbody>
                </table>
            </div>
            )}
        </div>

        <div className="card">
        <h4>Completion by Test</h4>

        <div className="lab-completion-list">
            {[
            "PSD",
            "PARTICLE_DENSITY",
            "ATTERBERG",
            "SHRINKAGE_LIMIT",
            "TRIAXIAL_UU",
            "CONSOLIDATION",
            ].map((type) => {
            const typeTests = tests.filter(
                (test) => test.test_type === type
            );

            const completed = typeTests.filter(
                (test) =>
                test.status === "APPROVED" ||
                test.status === "PUBLISHED"
            ).length;

            const total = typeTests.length;

            const percentage =
                total === 0
                ? 0
                : Math.round((completed / total) * 100);

            const label = type
                .replace(/_/g, " ")
                .replace("PSD", "Particle Size Distribution");

            return (
                <div
                key={type}
                className="lab-completion-item"
                >
                <div className="lab-completion-header">
                    <span>{label}</span>
                    <strong>
                    {completed} / {total}
                    </strong>
                </div>

                <div className="lab-progress-track">
                    <div
                    className="lab-progress-fill"
                    style={{ width: `${percentage}%` }}
                    />
                </div>

                <div className="lab-completion-percent">
                    {percentage}% completed
                </div>
                </div>
            );
            })}
        </div>
        </div>
      </div>

      <div className="card">
        <h4>Controlled Result Path</h4>

        <p className="page-sub">
          Laboratory results will move through entry, QA, approval,
          and finalization.
        </p>
      </div>
    </div>
  );
}