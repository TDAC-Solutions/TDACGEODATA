/** Latest entry point - Portfolio Management Centre (Company Home) */
import { useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { useAuth } from "../auth/AuthContext";
import {
  getPortfolioSummary,
  type PortfolioProject,
} from "../api/portfolio";

interface Project {
  number: string;
  name: string;
  client: string;
  location: string;
  stage: string;
  status: string;
  dataSummary: string;
}

interface Stat {
  label: string;
  value: string;
  chip: string;
  tone: string;
}

const ALL_STATUS = "all";

// Single source of truth for how raw ISSUE_STATUS values roll up into the
// buckets the UI shows.
//
// The cards and this table used to declare their own groupings separately,
// so one project could read "Completed" on a card and "Unspecified" in the
// table below it. Both now derive from this map, so they cannot disagree.
const STATUS_BUCKETS: Record<string, string[]> = {
  "In progress": ["Draft", "For Review", "In Progress"],
  "Pending Mobilization": ["Pending Mobilization"],
  // Client Issue means awaiting the client, not behind schedule, so it is
  // not counted as Delayed. Superseded means a later revision replaced the
  // report, which is not the same as delivered. Both land in the catch-all
  // rather than being mislabelled.
  Delayed: ["Delayed"],
  "On Hold": ["On Hold"],
  Completed: ["Final", "Completed"],
  Delivered: ["Delivered"],
  // Catch-all so the rows above always sum to the "All Projects" card.
  // Without it a project with no metadata row is invisible here.
  Unspecified: ["Unspecified", "Client Issue", "Superseded", "VOID"],
};

const STATUS_ROWS = Object.keys(STATUS_BUCKETS);

// Free-text match across the fields shown in the table. An empty or
// whitespace-only needle matches everything rather than nothing. Module
// scope: it closes over nothing, so useMemo does not need it as a dep.
function matchesQuery(project: Project, needle: string): boolean {
  const term = needle.trim().toLowerCase();

  if (!term) return true;

  return [project.number, project.name, project.client, project.location]
    .join(" ")
    .toLowerCase()
    .includes(term);
}

export function PortfolioPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [totalProjects, setTotalProjects] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // The Topbar writes ?q=, so the URL is the source of truth for the
  // search term. That makes a search from anywhere land here with the
  // filter applied, and keeps the filter across reloads and back/forward.
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") ?? "";
  const [statusFilter, setStatusFilter] = useState(ALL_STATUS);
  const [statusCounts, setStatusCounts] = useState<Record<string, number>>({});

  function setQuery(next: string) {
    // replace:true so typing does not flood the history stack.
    if (next) {
      setSearchParams({ q: next }, { replace: true });
    } else {
      setSearchParams({}, { replace: true });
    }
  }

  // Distinct statuses actually present, so the filter can never offer a
  // value that matches no row.
  const statusOptions = useMemo(
    () => Array.from(new Set(projects.map((p) => p.status))).sort(),
    [projects]
  );

  const visibleProjects = useMemo(
    () =>
      projects.filter(
        (project) =>
          matchesQuery(project, query) &&
          (statusFilter === ALL_STATUS || project.status === statusFilter)
      ),
    [projects, query, statusFilter]
  );

  useEffect(() => {
    async function loadPortfolio() {
      try {
        setLoading(true);
        setError("");

        const data = await getPortfolioSummary();

        const mappedProjects: Project[] = data.projects.map(
          (project: PortfolioProject) => ({
            number: String(project.PROJ_ID),
            name: project.PROJ_NAME ?? "—",
            client: project.PROJ_CLNT ?? "—",
            location: project.PROJ_LOC ?? "—",
            stage: "—",
            // Real issue status from PROJ_METADATA. Hardcoding "—" here
            // made the status filter permanently inert.
            status: project.ISSUE_STATUS ?? "—",
            dataSummary: "—",
          })
        );

        setProjects(mappedProjects);
        setTotalProjects(data.total_projects);
        setStatusCounts(data.status_counts ?? {});
      } catch (err) {
        console.error("Failed to load portfolio:", err);

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load portfolio data"
        );
      } finally {
        setLoading(false);
      }
    }

    loadPortfolio();
  }, []);

  // Card buckets are derived from the live ISSUE_STATUS tally rather than
  // a hardcoded vocabulary that no row could ever match.
  // Sum the raw statuses that roll up into one named bucket.
  const countOf = (bucket: string) =>
    (STATUS_BUCKETS[bucket] ?? []).reduce(
      (sum, status) => sum + (statusCounts[status] ?? 0),
      0,
    );

  const stats: Stat[] = [
    {
      label: "All Projects",
      value:
        totalProjects === null ? "—" : String(totalProjects),
      chip: "Searchable database",
      tone: "chip-info",
    },
    {
      label: "In Progress",
      value: String(countOf("In progress")),
      chip: "Active",
      tone: "chip-ok",
    },
    {
      label: "Pending / Delayed",
      value: String(countOf("Pending Mobilization") + countOf("Delayed")),
      chip: "Attention",
      tone: "chip-warn",
    },
    {
      label: "Completed / Delivered",
      value: String(countOf("Completed") + countOf("Delivered")),
      chip: "Archive",
      tone: "chip-muted",
    },
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">
            <b>COMPANY HOME</b>
          </div>

          <h1 className="page-title">
            Portfolio Management Centre
          </h1>

          {user && (
            <p className="page-sub">
              Welcome, <b>{user.username}</b>. Role:{" "}
              <b>{user.role}</b>. User ID: <b>{user.id}</b>
            </p>
          )}

          <p className="page-sub">
            The company project register. Search any historical or
            active project, inspect status and data availability, or
            create a new project directly in the database.
          </p>
        </div>

        <div className="actions">
          <button
            type="button"
            className="btn"
            disabled
            title="Importing legacy registers is not available in this version."
          >
            Import legacy registers
          </button>

          <button
            type="button"
            className="btn btn-primary"
            onClick={() => navigate("/projects/new")}
          >
            + Add New Project
          </button>
        </div>
      </div>

      <div className="grid grid-4">
        {stats.map((s) => (
          <div className="panel metric" key={s.label}>
            <div className="panel-body">
              <small>{s.label}</small>

              <div className="metric-num">
                {s.value}
              </div>

              <span className={`chip ${s.tone}`}>
                {s.chip}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-23">
        <div className="panel">
          <div className="panel-head no-divider">
            <h3 className="panel-title">
              Project Register
            </h3>

            <div className="actions">
              <select
                className="btn"
                aria-label="Filter projects by status"
                value={statusFilter}
                onChange={(event) =>
                  setStatusFilter(event.target.value)
                }
              >
                <option value={ALL_STATUS}>All status</option>

                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>

              <input
                type="search"
                className="search"
                placeholder="Search project no., name, place..."
                aria-label="Search projects"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
          </div>

          <div className="panel-body table-scroll">
            <table className="dtable register-table">
              <thead>
                <tr>
                  <th>Project No.</th>
                  <th>Project / Client</th>
                  <th>Location</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th>Data</th>
                  <th></th>
                </tr>
              </thead>

              <tbody>
                {loading ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="empty-row"
                    >
                      Loading project data...
                    </td>
                  </tr>
                ) : error ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="empty-row"
                    >
                      {error}
                    </td>
                  </tr>
                ) : projects.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="empty-row"
                    >
                      No data available in the database.
                    </td>
                  </tr>
                ) : visibleProjects.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      className="empty-row"
                    >
                      No project matches this search or status.
                    </td>
                  </tr>
                ) : (
                  visibleProjects.map((p) => (
                    <tr key={p.number}>
                      <td>
                        <b>{p.number}</b>
                      </td>

                      <td>
                        {p.name}
                        <br />
                        <small>{p.client}</small>
                      </td>

                      <td>{p.location}</td>

                      <td>{p.stage}</td>

                      <td>{p.status}</td>

                      <td>{p.dataSummary}</td>

                      <td></td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-head no-divider">
            <h3 className="panel-title">
              Portfolio Status
            </h3>
          </div>

          <div className="panel-body">
            <table className="stat-mini">
              <tbody>
                {STATUS_ROWS.map((label) => {
                  // Same helper the cards use, so the table and the cards
                  // can never disagree about a project's bucket.
                  const count = countOf(label);

                  return (
                    <tr key={label}>
                      <td>{label}</td>
                      <td>
                        <b>{count}</b>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            <p className="warning-note">
              Management rule: project status is derived from
              dates/workflow where possible; manual status changes
              require a reason.
            </p>
          </div>
        </div>
      </div>
    </>
  );
}