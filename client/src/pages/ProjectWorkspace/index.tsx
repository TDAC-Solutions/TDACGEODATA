import { useState, useEffect } from "react";
import { useParams } from "react-router-dom";
import {
  getProject,
  getProjectLocas,
  type LocaRecord,
  type ProjectRecord,
} from "../../api/projects";
import { WORKSPACE_TABS, getTabLabel } from "./types";
import { Overview } from "./Overview";
import { FieldData } from "./FieldData";
import { LabData } from "./LabData/index";
import { ProcessedData } from "./ProcessedData";
import { InterpretationGroundModel } from "./InterpretationGroundModel";
import { DesignParameters } from "./DesignParameters";
import { Design } from "./Design";
import { Reports } from "./Reports";
import { PlaceholderPanel } from "./PlaceholderPanel";
import { AttachmentsPanel } from "./AttachmentsPanel";
import { useUnsavedGuard } from "./UnsavedChanges";

export function ProjectWorkspacePage() {
  // No provider here on purpose: it lives in App, above the router, so the
  // Topbar shares the same registry. A provider here would shadow it and the
  // Topbar would never see a dirty grid.
  return <ProjectWorkspace />;
}

function ProjectWorkspace() {
  const confirmDiscard = useUnsavedGuard();
  const { projectId } = useParams();
  const [activeTab, setActiveTab] = useState("overview");

  const [project, setProject] = useState<ProjectRecord | null>(null);
  const [projectLoading, setProjectLoading] = useState(true);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [editingProject, setEditingProject] = useState(false);

  const [locas, setLocas] = useState<LocaRecord[]>([]);
  const [selectedLocaId, setSelectedLocaId] = useState<string | null>(null);
  const [locasLoading, setLocasLoading] = useState(false);
  const [locasError, setLocasError] = useState<string | null>(null);

  // Overview first: it is the borehole report, the thing someone opening
  // Field Data almost always came to read. The entry modules below it are for
  // making changes.
  const [activeFieldModule, setActiveFieldModule] = useState("overview");
  const [addingLoca, setAddingLoca] = useState(false);

  useEffect(() => {
    if (!projectId) {
      setProjectLoading(false);
      setProjectError("No project ID was provided.");
      return;
    }

    const id = projectId;

    // Set by the cleanup below. A slow request for the project you just
    // navigated away from must not be allowed to paint over the one you are
    // looking at now -- without this, switching A -> B on a slow link leaves
    // A's name and A's error state sitting under B's route.
    let cancelled = false;

    async function loadProject() {
      try {
        setProjectLoading(true);
        setProjectError(null);

        const data = await getProject(id);
        if (cancelled) return;
        setProject(data);
      } catch (error) {
        if (cancelled) return;
        console.error("Failed to load project:", error);
        setProjectError("Unable to load project.");
      } finally {
        if (!cancelled) setProjectLoading(false);
      }
    }

    loadProject();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Re-fetches the location list; the reload key lets the effect-driven
  // loader and the post-import refresh share one path without
  // duplicating the fetch in multiple callbacks.
  const [locasReloadKey, setLocasReloadKey] = useState(0);
  const [showAttachments, setShowAttachments] = useState(false);

  // Everything scoped to a project is dropped when the project changes.
  //
  // Lab Data additionally carries key={projectId} below, because it keeps
  // local state that belongs to one project -- the open sub-tab, the
  // selected test in Results Entry, the Sample Register location filter,
  // the Historic Data filter. React reuses a component when only a route
  // param changes, so without the key project B inherits project A
  // selections. Remounting on projectId is the whole fix.
  //
  // The attachment panel is mounted at workspace level, so leaving it open
  // across a project switch would silently refetch it against the new
  // project and retitle itself.
  useEffect(() => {
    setActiveTab("overview");
    setActiveFieldModule("overview");
    setShowAttachments(false);
    setAddingLoca(false);
    setEditingProject(false);
    setSelectedLocaId(null);
    setLocas([]);
    setProject(null);
    setLocasError(null);
  }, [projectId]);

  function loadLocasAgain() {
    setLocasReloadKey((key) => key + 1);
  }

  useEffect(() => {
    if (!projectId) {
      return;
    }

    const id = projectId;

    // Same reason as loadProject above. This one also auto-selects the first
    // borehole, so a stale response is worse: it can quietly repoint the
    // Field Data location selector at a borehole belonging to another project.
    let cancelled = false;

    async function loadLocas() {
      try {
        setLocasLoading(true);
        setLocasError(null);

        const data = await getProjectLocas(id);
        if (cancelled) return;
        setLocas(data);

        setSelectedLocaId((current) => {
          if (current && data.some((loca) => loca.loca_id === current)) {
            return current;
          }

          return data.length > 0 ? data[0].loca_id : null;
        });
      } catch (error) {
        if (cancelled) return;
        console.error("Failed to load LOCAs:", error);
        setLocasError("Unable to load project locations.");
      } finally {
        if (!cancelled) setLocasLoading(false);
      }
    }

    loadLocas();
    return () => {
      cancelled = true;
    };
  }, [projectId, locasReloadKey]);

  // Called after a new location is created from the Overview tab so the
  // Field Data location list is available immediately, without an
  // unrelated page refresh.
  function handleLocaCreated(newLoca: LocaRecord) {
    setLocas((current) => [...current, newLoca].sort((a, b) =>
      a.loca_id.localeCompare(b.loca_id)
    ));
    setSelectedLocaId(newLoca.loca_id);
  }

  return (
    <>
      {/* Project header */}
      <div className="projectbar">
        <div>
          <div className="eyebrow">PROJECT WORKSPACE</div>

          <h1 className="projectbar-title">
            {projectLoading
              ? "Loading…"
              : project?.project_name ?? projectId ?? "—"}
          </h1>

          <div className="projectbar-meta">
            {projectLoading
              ? "Loading project details…"
              : projectError
              ? projectError
              : `${project?.project_id ?? "—"} · ${
                  project?.project_client || "No client"
                } · ${project?.project_location || "No location"}`}
          </div>
        </div>

        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={() => setShowAttachments(true)}
          >
            Attachments
          </button>

          <button
            type="button"
            className="btn"
            disabled
            title="QA / Issues is not available in this version."
          >
            QA / Issues
          </button>
        </div>
      </div>

      {/* Main workspace navigation */}
      <nav className="tabs" role="tablist" aria-label="Project workspace sections">
        {WORKSPACE_TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={activeTab === tab.id}
            className={`tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => {
              if (tab.id === activeTab) return;
              // Leaves the entry grid mounted -> unmounted, so its rows go.
              if (!confirmDiscard()) return;
              setActiveTab(tab.id);
            }}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      {/* Active workspace module */}
      {activeTab === "overview" ? (
        <Overview
          project={project}
          loading={projectLoading}
          error={projectError}
          projectId={projectId}
          editing={editingProject}
          onEditingChange={setEditingProject}
          onProjectUpdated={setProject}
          addingLoca={addingLoca}
          onAddingLocaChange={setAddingLoca}
          onLocaCreated={handleLocaCreated}
          onLocasImported={loadLocasAgain}
          locas={locas}
        />
      ) : activeTab === "field" ? (
        <FieldData
          projectId={projectId}
          locas={locas}
          selectedLocaId={selectedLocaId}
          loading={locasLoading}
          error={locasError}
          onSelectLoca={(locaId) => {
            if (locaId === selectedLocaId) return;
            // Changes which borehole the grid is bound to, which reloads it.
            if (!confirmDiscard()) return;
            setSelectedLocaId(locaId);
          }}
          activeModule={activeFieldModule}
          onSelectModule={setActiveFieldModule}
        />
      ) : activeTab === "lab" ? (
        <LabData key={projectId} projectId={projectId} />
      ) : activeTab === "processed" ? (
        <ProcessedData />
      ) : activeTab === "interpretation" ? (
        <InterpretationGroundModel />
      ) : activeTab === "parameters" ? (
        <DesignParameters />
      ) : activeTab === "design" ? (
        <Design />
      ) : activeTab === "reports" ? (
        <Reports />
      ) : (
        <PlaceholderPanel title={getTabLabel(activeTab)} />
      )}

      {showAttachments && (
        <AttachmentsPanel
          projectId={projectId}
          scope={{ kind: "project" }}
          onClose={() => setShowAttachments(false)}
        />
      )}
    </>
  );
}
