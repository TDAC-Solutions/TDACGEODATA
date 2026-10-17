import { useState, useEffect } from "react";
import {
  getProjectMetadata,
  updateProjectOverview,
  type LocaRecord,
  type ProjectMetadataRecord,
  type ProjectRecord,
} from "../../api/projects";
import {
  createLocaFromExcel,
  SpreadsheetFilePicker,
  type ImportedWorkbook,
} from "../../spreadsheet";
import { AddLocaModal } from "./AddLocaModal";

interface OverviewProps {
  project: ProjectRecord | null;
  loading: boolean;
  error: string | null;
  projectId: string | undefined;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  onProjectUpdated: (project: ProjectRecord) => void;
  addingLoca: boolean;
  onAddingLocaChange: (addingLoca: boolean) => void;
  onLocaCreated: (loca: LocaRecord) => void;
  onLocasImported?: () => void;
  locas: LocaRecord[];
}

export function Overview({
  project,
  loading,
  error,
  projectId,
  editing,
  onEditingChange,
  onProjectUpdated,
  addingLoca,
  onAddingLocaChange,
  onLocaCreated,
  onLocasImported,
  locas,
}: OverviewProps) {
  const [projectName, setProjectName] = useState("");
  const [projectLocation, setProjectLocation] = useState("");
  const [projectClient, setProjectClient] = useState("");
  const [metadata, setMetadata] =
    useState<ProjectMetadataRecord | null>(null);

  const [metadataLoading, setMetadataLoading] = useState(false);
  const [metadataError, setMetadataError] = useState<string | null>(null);

  const [consultantName, setConsultantName] = useState("");
  const [contractorName, setContractorName] = useState("");

  const [roadReference, setRoadReference] = useState("");
  const [chainageText, setChainageText] = useState("");
  const [structureReference, setStructureReference] = useState("");
  const [selectedBoreholes, setSelectedBoreholes] = useState("");

  const [reportType, setReportType] = useState("");
  const [reportTitle, setReportTitle] = useState("");
  const [reportVolumeTitle, setReportVolumeTitle] = useState("");
  const [documentReference, setDocumentReference] = useState("");
  const [revision, setRevision] = useState("");
  const [reportDate, setReportDate] = useState("");
  const [issueStatus, setIssueStatus] = useState("");

  const [tdacCompanyName, setTdacCompanyName] = useState("");
  const [groundwaterBasis, setGroundwaterBasis] = useState("");

  const [designStandardBasis, setDesignStandardBasis] = useState("");
  const [factorOfSafetyBasis, setFactorOfSafetyBasis] = useState("");
  const [loadCombinationBasis, setLoadCombinationBasis] = useState("");
  const [
    constructionVerificationRequirement,
    setConstructionVerificationRequirement,
  ] = useState("");
  const [pileLoadTestRequirement, setPileLoadTestRequirement] =
    useState("");
    
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Feature 13: the investigation summary is derived from the LOCA records
  // the workspace already holds, so it can never drift from the real data
  // and needs no second request. Termination depths arrive as floats over
  // the API but a depth of NaN or 0 is not a measurement, so those rows are
  // left out of the range rather than being allowed to skew it.
  //
  // BH is the only location type that is drilled, so it is the only one a
  // termination depth describes. SPT and CPT are in-situ tests terminated
  // at whatever the rig reached, and Sampling/Other are not excavations at
  // all, so counting every row as a borehole would overstate the drilling
  // on a project and put the count at odds with the depths beside it.
  //
  // The compare is case-insensitive and trimmed because nothing at the
  // database stops a pre-dropdown row reading "bh" or "BH ": LOCA_TYPE has
  // no CHECK constraint, so such rows can exist from manual entry or an
  // Excel import. Matching those exactly would silently drop them from the
  // count while they still appear in the table below.
  const isBorehole = (loca: LocaRecord) =>
    (loca.loca_type || "").trim().toUpperCase() === "BH";

  const boreholes = locas.filter(isBorehole);
  const otherLocations = locas.length - boreholes.length;

  const measuredDepths = (rows: LocaRecord[]) =>
    rows
      .map((loca) => loca.final_depth)
      .filter(
        (depth): depth is number =>
          depth !== null &&
          depth !== undefined &&
          Number.isFinite(depth) &&
          depth > 0
      );

  const boreholeDepths = measuredDepths(boreholes);

  const deepestDepth = boreholeDepths.length
    ? Math.max(...boreholeDepths)
    : null;
  const shallowestDepth = boreholeDepths.length
    ? Math.min(...boreholeDepths)
    : null;
  const boreholesWithoutDepth = boreholes.length - boreholeDepths.length;

  function formatDepth(depth: number | null, digits: number) {
    return depth === null ? "—" : `${depth.toFixed(digits)} m`;
  }

  function formatCoordinate(value: number | null | undefined) {
    if (value === null || value === undefined) {
      return "—";
    }

    return Number(value).toFixed(3);
  }

  useEffect(() => {
    // Drop the previous project's metadata up front. Overview stays mounted
    // across a project change, so without this the report block keeps
    // rendering project A's client, road reference and revision while
    // project B loads -- and the Edit Project button is disabled until B's
    // metadata arrives, which makes that stale state look plausible.
    setMetadata(null);
    setMetadataError(null);

    if (!projectId) {
      return;
    }

    // A late response for the project we just left must not win the race
    // against the one we are actually opening.
    let cancelled = false;

    async function loadMetadata() {
      try {
        setMetadataLoading(true);
        setMetadataError(null);

        const data = await getProjectMetadata(projectId);
        if (cancelled) return;
        setMetadata(data);
      } catch (error) {
        if (cancelled) return;
        console.error("Failed to load project metadata:", error);
        setMetadataError("Unable to load project metadata.");
      } finally {
        if (!cancelled) setMetadataLoading(false);
      }
    }

    loadMetadata();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const [importBusy, setImportBusy] = useState(false);
  const [importNotice, setImportNotice] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  async function handleExcelImported(workbook: ImportedWorkbook) {
    if (!projectId) {
      setImportError("No project ID was provided.");
      return;
    }

    try {
      setImportBusy(true);
      setImportError(null);
      setImportNotice(null);

      const result = await createLocaFromExcel(projectId, {
        borehole_type: "BH",
        workbook,
      });

      setImportNotice(
        `Imported ${result.borehole_id}: ${result.geol_rows} borelog, ` +
        `${result.core_rows} rock profile, ${result.spt_rows} SPT rows.`
      );
      onLocasImported?.();
    } catch (error) {
      console.error("Failed to import location from Excel:", error);
      setImportError(
        error instanceof Error
          ? error.message
          : "Unable to import this workbook."
      );
    } finally {
      setImportBusy(false);
    }
  }

function startEditing() {
  if (!project || !metadata) {
    return;
  }

  setProjectName(project.project_name);
  setProjectLocation(project.project_location);
  setProjectClient(project.project_client);
  setConsultantName(project.consultant_name);
  setContractorName(project.contractor_name);

  setRoadReference(metadata?.road_reference || "");
  setChainageText(metadata?.chainage_text || "");
  setStructureReference(metadata?.structure_reference || "");
  setSelectedBoreholes(metadata?.selected_boreholes || "");

  setReportType(metadata?.report_type || "");
  setReportTitle(metadata?.report_title || "");
  setReportVolumeTitle(metadata?.report_volume_title || "");
  setDocumentReference(metadata?.document_reference || "");
  setRevision(metadata?.revision || "");
  setReportDate(metadata?.report_date || "");
  setIssueStatus(metadata?.issue_status || "");

  setTdacCompanyName(metadata?.tdac_company_name || "");
  setGroundwaterBasis(metadata?.groundwater_basis || "");

  setDesignStandardBasis(metadata?.design_standard_basis || "");
  setFactorOfSafetyBasis(metadata?.factor_of_safety_basis || "");
  setLoadCombinationBasis(metadata?.load_combination_basis || "");
  setConstructionVerificationRequirement(
    metadata?.construction_verification_requirement || ""
  );
  setPileLoadTestRequirement(
    metadata?.pile_load_test_requirement || ""
  );

  setSaveError(null);
  onEditingChange(true);
}

  function cancelEditing() {
    setSaveError(null);
    onEditingChange(false);
  }

  async function saveChanges() {
  if (!projectId) {
    setSaveError("No project ID was provided.");
    return;
  }

  if (!projectName.trim()) {
    setSaveError("Project name is required.");
    return;
  }

  if (!projectLocation.trim()) {
    setSaveError("Project location is required.");
    return;
  }

  if (!projectClient.trim()) {
    setSaveError("Project client is required.");
    return;
  }

  if (!consultantName.trim()) {
    setSaveError("Consultant name is required.");
    return;
  }

  if (!contractorName.trim()) {
    setSaveError("Contractor name is required.");
    return;
  }

  if (!roadReference.trim()) {
    setSaveError("Road / Highway Reference is required.");
    return;
  }

  if (!chainageText.trim()) {
    setSaveError("Chainage / Chainage Range is required.");
    return;
  }

  if (!structureReference.trim()) {
    setSaveError("Structure / Location Reference is required.");
    return;
  }

  if (!selectedBoreholes.trim()) {
    setSaveError("Selected Borehole IDs are required.");
    return;
  }

  if (!reportType) {
    setSaveError("Report Type is required.");
    return;
  }

  if (!reportTitle.trim()) {
    setSaveError("Report Title is required.");
    return;
  }

  if (!reportVolumeTitle.trim()) {
    setSaveError("Report Volume Title is required.");
    return;
  }

  if (!documentReference.trim()) {
    setSaveError("TDAC Document Reference is required.");
    return;
  }

  if (!revision.trim()) {
    setSaveError("Revision is required.");
    return;
  }

  if (!reportDate) {
    setSaveError("Report Date is required.");
    return;
  }

  if (!issueStatus) {
    setSaveError("Issue Status is required.");
    return;
  }

  if (!tdacCompanyName.trim()) {
    setSaveError("TDAC Company Name is required.");
    return;
  }

  if (!groundwaterBasis.trim()) {
    setSaveError("Groundwater Basis is required.");
    return;
  }

  if (reportType === "Design") {
    if (!designStandardBasis.trim()) {
      setSaveError("Design Standard Basis is required.");
      return;
    }

    if (!factorOfSafetyBasis.trim()) {
      setSaveError("Factor of Safety Basis is required.");
      return;
    }

    if (!loadCombinationBasis.trim()) {
      setSaveError("Load Combination Basis is required.");
      return;
    }

    if (!constructionVerificationRequirement.trim()) {
      setSaveError(
        "Construction Verification Requirement is required."
      );
      return;
    }

    if (!pileLoadTestRequirement.trim()) {
      setSaveError("Pile Load Test Requirement is required.");
      return;
    }
  }

  try {
    setSaving(true);
    setSaveError(null);

    const updatedProject = await updateProjectOverview(projectId, {
      project_name: projectName.trim(),
      project_location: projectLocation.trim(),
      project_client: projectClient.trim(),
      consultant_name: consultantName.trim(),
      contractor_name: contractorName.trim(),

      road_reference: roadReference.trim(),
      chainage_text: chainageText.trim(),
      structure_reference: structureReference.trim(),
      selected_boreholes: selectedBoreholes.trim(),

      report_type: reportType,
      report_title: reportTitle.trim(),
      report_volume_title: reportVolumeTitle.trim(),
      document_reference: documentReference.trim(),
      revision: revision.trim(),
      report_date: reportDate,
      issue_status: issueStatus,

      tdac_company_name: tdacCompanyName.trim(),
      groundwater_basis: groundwaterBasis.trim(),

      design_standard_basis: designStandardBasis.trim(),
      factor_of_safety_basis: factorOfSafetyBasis.trim(),
      load_combination_basis: loadCombinationBasis.trim(),
      construction_verification_requirement:
        constructionVerificationRequirement.trim(),
      pile_load_test_requirement:
        pileLoadTestRequirement.trim(),
    });

    onProjectUpdated(updatedProject);

    setMetadata((current) =>
      current
        ? {
            ...current,
            road_reference: roadReference.trim(),
            chainage_text: chainageText.trim(),
            structure_reference: structureReference.trim(),
            selected_boreholes: selectedBoreholes.trim(),
            report_type: reportType,
            report_title: reportTitle.trim(),
            report_volume_title: reportVolumeTitle.trim(),
            document_reference: documentReference.trim(),
            revision: revision.trim(),
            report_date: reportDate,
            issue_status: issueStatus,
            tdac_company_name: tdacCompanyName.trim(),
            groundwater_basis: groundwaterBasis.trim(),
            design_standard_basis: designStandardBasis.trim(),
            factor_of_safety_basis: factorOfSafetyBasis.trim(),
            load_combination_basis: loadCombinationBasis.trim(),
            construction_verification_requirement:
              constructionVerificationRequirement.trim(),
            pile_load_test_requirement:
              pileLoadTestRequirement.trim(),
          }
        : current
    );

    onEditingChange(false);
  } catch (error) {
    console.error("Failed to update project overview:", error);

    setSaveError(
      error instanceof Error
        ? error.message
        : "Unable to save project changes."
    );
  } finally {
    setSaving(false);
  }
} return (
    <section className="panel">
      <div className="panel-head">
        <h2 className="panel-title">Project Information</h2>

        {/* Edit seeds every field from `metadata`, so it must stay hidden
            until that has actually arrived. It used to be gated only on the
            project, leaving a window -- wider on a slow connection -- where
            `project` had resolved but `metadata` had not. startEditing then
            filled all fifteen fields from `metadata?.x || ""`, and saving
            sent them back as empty strings: clicking Edit and changing one
            field wiped the entire Report & Document Control block. */}
        {!loading &&
          !error &&
          project &&
          metadata &&
          !metadataLoading &&
          !metadataError &&
          !editing && (
            <button type="button" className="btn" onClick={startEditing}>
              Edit Project
            </button>
          )}
      </div>

      <div className="panel-body">
        {loading && <p className="page-sub">Loading project information…</p>}

        {!loading && error && <p className="page-sub">{error}</p>}

        {!loading && !error && project && !editing && (
          <div className="overview-grid">

            {/* PROJECT */}
            <div className="overview-section">
              <div className="overview-section-title">
              Project Details
              </div>

              <div className="overview-fields">
                <div>
                  <span>Project ID</span>
                  <strong>{project.project_id}</strong>
                </div>

                <div>
                  <span>Project Title</span>
                  <strong>{project.project_name || "—"}</strong>
                </div>

                <div>
                  <span>Project Type</span>
                  <strong>
                    {project.project_type === "LAB_ONLY"
                      ? "Lab Only"
                      : project.project_type === "REPORT_ONLY"
                        ? "Report Only"
                        : project.project_type === "LAB_AND_REPORT"
                          ? "Lab + Report"
                          : "—"}
                  </strong>
                </div>

                <div>
                  <span>Client Name</span>
                  <strong>{project.project_client || "—"}</strong>
                </div>

                <div>
                  <span>Consultant Name</span>
                  <strong>{project.consultant_name || "—"}</strong>
                </div>

                <div>
                  <span>Contractor Name</span>
                  <strong>{project.contractor_name || "—"}</strong>
                </div>

                <div>
                  <span>Site Location</span>
                  <strong>{project.project_location || "—"}</strong>
                </div>
              </div>
            </div>

            {/* SITE / INVESTIGATION */}
            <div className="overview-section">
              <div className="overview-section-title">
                Site &amp; Investigation
              </div>

              <div className="overview-fields">
                <div>
                  <span>Road / Highway Reference</span>
                  <strong>{metadata?.road_reference || "—"}</strong>
                </div>

                <div>
                  <span>Chainage / Range</span>
                  <strong>{metadata?.chainage_text || "—"}</strong>
                </div>

                <div>
                  <span>Structure / Location</span>
                  <strong>{metadata?.structure_reference || "—"}</strong>
                </div>

                <div>
                  <span>Selected Boreholes</span>
                  <strong>
                    {/* Real locations beat the typed field. The metadata
                        value is text entered at project creation, so it
                        goes stale the moment a borehole is added; it is
                        kept only as the fallback for a project that is
                        planned but not yet drilled. */}
                    {boreholes.length > 0
                      ? boreholes.map((loca) => loca.loca_id).join(", ")
                      : metadata?.selected_boreholes || "—"}
                  </strong>
                </div>
              </div>
            </div>

            {/* INVESTIGATION SUMMARY - derived from the LOCA records.
                Metrics only. The full location table lives in the Locations
                panel below, next to the Add Location / Import actions,
                because that panel is what owns the LOCA records. */}
            <div className="overview-section overview-section-wide">
              <div className="overview-section-title">
                Investigation Summary
              </div>

              <div className="overview-fields overview-fields-three">
                <div>
                  <span>Total Boreholes</span>
                  <strong>{boreholes.length}</strong>
                </div>

                <div>
                  <span>Deepest Termination</span>
                  <strong>{formatDepth(deepestDepth, 2)}</strong>
                </div>

                <div>
                  <span>Shallowest Termination</span>
                  <strong>{formatDepth(shallowestDepth, 2)}</strong>
                </div>
              </div>

              {/* The depth range describes boreholes only, so any
                  non-borehole or unmeasured location is stated plainly
                  rather than allowed to make the three figures above look
                  like they describe different sets. */}
              {(otherLocations > 0 || boreholesWithoutDepth > 0) && (
                <p className="page-sub">
                  {otherLocations > 0 && (
                    <>
                      {otherLocations} non-borehole location
                      {otherLocations === 1 ? "" : "s"} counted separately
                      below.{" "}
                    </>
                  )}

                  {boreholesWithoutDepth > 0 && (
                    <>
                      {boreholesWithoutDepth} borehole
                      {boreholesWithoutDepth === 1 ? " has" : "s have"} no
                      recorded termination depth and
                      {boreholesWithoutDepth === 1 ? " is" : " are"} excluded
                      from the depth range.
                    </>
                  )}
                </p>
              )}

              {locas.length === 0 && (
                <p className="page-sub">
                  No investigation locations recorded yet. Add one from the
                  Locations panel below.
                </p>
              )}
            </div>

            {/* REPORT */}
            <div className="overview-section overview-section-wide">
              <div className="overview-section-title">
                Report &amp; Document Control
              </div>

              <div className="overview-fields overview-fields-five">
                <div>
                  <span>Report Type</span>
                  <strong>{metadata?.report_type || "—"}</strong>
                </div>

                <div>
                  <span>Report Title</span>
                  <strong>{metadata?.report_title || "—"}</strong>
                </div>

                <div>
                  <span>Volume Title</span>
                  <strong>{metadata?.report_volume_title || "—"}</strong>
                </div>

                <div>
                  <span>Document Reference</span>
                  <strong>{metadata?.document_reference || "—"}</strong>
                </div>

                <div>
                  <span>Revision</span>
                  <strong>{metadata?.revision || "—"}</strong>
                </div>

                <div>
                  <span>Report Date</span>
                  <strong>{metadata?.report_date || "—"}</strong>
                </div>

                <div>
                  <span>Issue Status</span>
                  <strong>{metadata?.issue_status || "—"}</strong>
                </div>
              </div>
            </div>

            {/* TDAC */}
            <div className="overview-section">
              <div className="overview-section-title">
                TDAC &amp; Groundwater
              </div>

              <div className="overview-fields">
                <div>
                  <span>TDAC Company Name</span>
                  <strong>{metadata?.tdac_company_name || "—"}</strong>
                </div>

                <div>
                  <span>Groundwater Basis</span>
                  <strong>{metadata?.groundwater_basis || "—"}</strong>
                </div>
              </div>
            </div>

            {/* DESIGN BASIS */}
            <div className="overview-section">
              <div className="overview-section-title">
                Design Basis
              </div>

              <div className="overview-fields">
                <div>
                  <span>Design Standard</span>
                  <strong>{metadata?.design_standard_basis || "—"}</strong>
                </div>

                <div>
                  <span>Factor of Safety</span>
                  <strong>{metadata?.factor_of_safety_basis || "—"}</strong>
                </div>

                <div>
                  <span>Load Combination</span>
                  <strong>{metadata?.load_combination_basis || "—"}</strong>
                </div>

                <div>
                  <span>Construction Verification</span>
                  <strong>
                    {metadata?.construction_verification_requirement || "—"}
                  </strong>
                </div>

                <div>
                  <span>Pile Load Test</span>
                  <strong>{metadata?.pile_load_test_requirement || "—"}</strong>
                </div>
              </div>
            </div>

          </div>
        )}

        {!loading && !error && project && editing && (
  <div className="overview-edit-grid">

    {/* PROJECT DETAILS */}
    <div className="overview-section overview-section-wide">
      <div className="overview-section-title">
        Project Details
      </div>

      <div className="overview-edit-fields">
        <label>
          <span>Project ID</span>
          <input
            type="text"
            value={project.project_id}
            disabled
          />
        </label>

        <label>
          <span>Project Title</span>
          <input
            type="text"
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
          />
        </label>

        <label>
          <span>Site Location</span>
          <input
            type="text"
            value={projectLocation}
            onChange={(event) =>
              setProjectLocation(event.target.value)
            }
          />
        </label>

        <label>
          <span>Client Name</span>
          <input
            type="text"
            value={projectClient}
            onChange={(event) =>
              setProjectClient(event.target.value)
            }
          />
        </label>

        <label>
          <span>Consultant Name</span>
          <input
            type="text"
            value={consultantName}
            onChange={(event) =>
              setConsultantName(event.target.value)
            }
          />
        </label>

        <label>
          <span>Contractor Name</span>
          <input
            type="text"
            value={contractorName}
            onChange={(event) =>
              setContractorName(event.target.value)
            }
          />
        </label>
      </div>
    </div>

    {/* SITE / INVESTIGATION */}
    <div className="overview-section">
      <div className="overview-section-title">
        Site &amp; Investigation
      </div>

      <div className="overview-edit-fields">
        <label>
          <span>Road / Highway Reference</span>
          <input
            type="text"
            value={roadReference}
            onChange={(event) =>
              setRoadReference(event.target.value)
            }
          />
        </label>

        <label>
          <span>Chainage / Range</span>
          <input
            type="text"
            value={chainageText}
            onChange={(event) =>
              setChainageText(event.target.value)
            }
          />
        </label>

        <label>
          <span>Structure / Location</span>
          <input
            type="text"
            value={structureReference}
            onChange={(event) =>
              setStructureReference(event.target.value)
            }
          />
        </label>

        <label>
          <span>Selected Boreholes</span>
          <input
            type="text"
            value={selectedBoreholes}
            onChange={(event) =>
              setSelectedBoreholes(event.target.value)
            }
          />
        </label>
      </div>
    </div>

    {/* TDAC */}
    <div className="overview-section">
      <div className="overview-section-title">
        TDAC &amp; Groundwater
      </div>

      <div className="overview-edit-fields">
        <label>
          <span>TDAC Company Name</span>
          <input
            type="text"
            value={tdacCompanyName}
            onChange={(event) =>
              setTdacCompanyName(event.target.value)
            }
          />
        </label>

        <label>
          <span>Groundwater Basis</span>
          <textarea
            rows={2}
            value={groundwaterBasis}
            onChange={(event) =>
              setGroundwaterBasis(event.target.value)
            }
          />
        </label>
      </div>
    </div>

    {/* REPORT */}
    <div className="overview-section overview-section-wide">
      <div className="overview-section-title">
        Report &amp; Document Control
      </div>

      <div className="overview-edit-fields overview-edit-fields-five">
        <label>
          <span>Report Type</span>
          <select
            value={reportType}
            onChange={(event) =>
              setReportType(event.target.value)
            }
          >
            <option value="">Select report type</option>
            <option value="Factual">Factual</option>
            <option value="Interpretive">Interpretive</option>
            <option value="Design">Design</option>
            <option value="Final">Final</option>
          </select>
        </label>

        <label>
          <span>Report Title</span>
          <input
            type="text"
            value={reportTitle}
            onChange={(event) =>
              setReportTitle(event.target.value)
            }
          />
        </label>

        <label>
          <span>Volume Title</span>
          <input
            type="text"
            value={reportVolumeTitle}
            onChange={(event) =>
              setReportVolumeTitle(event.target.value)
            }
          />
        </label>

        <label>
          <span>Document Reference</span>
          <input
            type="text"
            value={documentReference}
            onChange={(event) =>
              setDocumentReference(event.target.value)
            }
          />
        </label>

        <label>
          <span>Revision</span>
          <input
            type="text"
            value={revision}
            onChange={(event) =>
              setRevision(event.target.value)
            }
          />
        </label>

        <label>
          <span>Report Date</span>
          <input
            type="date"
            value={reportDate}
            onChange={(event) =>
              setReportDate(event.target.value)
            }
          />
        </label>

        <label>
          <span>Issue Status</span>
          <select
            value={issueStatus}
            onChange={(event) =>
              setIssueStatus(event.target.value)
            }
          >
            <option value="">Select issue status</option>
            <option value="Draft">Draft</option>
            <option value="For Review">For Review</option>
            <option value="Client Issue">Client Issue</option>
            <option value="Final">Final</option>
            <option value="Superseded">Superseded</option>
          </select>
        </label>
      </div>
    </div>

    {/* DESIGN BASIS */}
    <div className="overview-section overview-section-wide">
      <div className="overview-section-title">
        Design Basis
      </div>

      <div className="overview-edit-fields">
        <label>
          <span>Design Standard</span>
          <textarea
            rows={2}
            value={designStandardBasis}
            onChange={(event) =>
              setDesignStandardBasis(event.target.value)
            }
          />
        </label>

        <label>
          <span>Factor of Safety</span>
          <textarea
            rows={2}
            value={factorOfSafetyBasis}
            onChange={(event) =>
              setFactorOfSafetyBasis(event.target.value)
            }
          />
        </label>

        <label>
          <span>Load Combination</span>
          <textarea
            rows={2}
            value={loadCombinationBasis}
            onChange={(event) =>
              setLoadCombinationBasis(event.target.value)
            }
          />
        </label>

        <label>
          <span>Construction Verification</span>
          <textarea
            rows={2}
            value={constructionVerificationRequirement}
            onChange={(event) =>
              setConstructionVerificationRequirement(
                event.target.value
              )
            }
          />
        </label>

        <label>
          <span>Pile Load Test</span>
          <textarea
            rows={2}
            value={pileLoadTestRequirement}
            onChange={(event) =>
              setPileLoadTestRequirement(
                event.target.value
              )
            }
          />
        </label>
      </div>
    </div>

    {saveError && (
      <div className="warning-note">
        {saveError}
      </div>
    )}

    <div
      className="actions"
      style={{ justifyContent: "flex-end" }}
    >
      <button
        type="button"
        className="btn"
        onClick={cancelEditing}
        disabled={saving}
      >
        Cancel
      </button>

      <button
        type="button"
        className="btn btn-primary"
        onClick={saveChanges}
        disabled={saving}
      >
        {saving ? "Saving…" : "Save Changes"}
      </button>
    </div>
  </div>
)}

        {!loading && !error && !project && (
          <p className="page-sub">Project information is unavailable.</p>
        )}
      </div>

      <section className="panel">
        <div className="panel-head">
          <h2 className="panel-title">Locations</h2>

          <div className="actions">
            <SpreadsheetFilePicker
              onParsed={(workbook) => handleExcelImported(workbook)}
              onError={(message) => {
                setImportNotice(null);
                setImportError(message);
              }}
              disabled={importBusy}
              label="Import from Excel"
              accept=".xlsx,.xlsm"
            />

            <button
              type="button"
              className="btn btn-primary"
              onClick={() => onAddingLocaChange(true)}
            >
              + Add Location
            </button>
          </div>
        </div>
        <div className="panel-body">
          <p className="page-sub">
            Add and manage investigation locations associated with this
            project.
          </p>

          {importBusy && (
            <p className="page-sub">Importing workbook...</p>
          )}

          {importNotice && (
            <div className="import-note" role="status">
              {importNotice}
            </div>
          )}

          {importError && (
            <div className="warning-note">{importError}</div>
          )}

          {locas.length === 0 ? (
            <div className="empty-state">
              <h3>No investigation locations</h3>

              <p>
                Add the first borehole or import a workbook to populate
                this list.
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="dtable">
                <thead>
                  <tr>
                    <th>Location ID</th>
                    <th>Type</th>
                    <th>Termination (m)</th>
                    <th>Ground Level / RL (m)</th>
                    <th>Groundwater (m bgl)</th>
                    <th>Easting</th>
                    <th>Northing</th>
                    <th>Latitude</th>
                    <th>Longitude</th>
                  </tr>
                </thead>

                <tbody>
                  {locas.map((loca) => (
                    <tr key={loca.loca_id}>
                      <td data-label="Location ID">
                        <b>{loca.loca_id}</b>
                      </td>

                      <td data-label="Type">{loca.loca_type || "—"}</td>

                      <td className="num" data-label="Termination (m)">
                        {formatDepth(
                          loca.final_depth !== null &&
                            loca.final_depth !== undefined &&
                            Number.isFinite(loca.final_depth)
                            ? Number(loca.final_depth)
                            : null,
                          2
                        )}
                      </td>

                      <td
                        className="num"
                        data-label="Ground Level / RL (m)"
                      >
                        {formatCoordinate(loca.ground_level)}
                      </td>

                      <td className="num" data-label="Groundwater (m bgl)">
                        {formatDepth(
                          loca.groundwater_depth !== null &&
                            loca.groundwater_depth !== undefined &&
                            Number.isFinite(loca.groundwater_depth)
                            ? Number(loca.groundwater_depth)
                            : null,
                          2
                        )}
                      </td>

                      <td className="num" data-label="Easting">
                        {formatCoordinate(loca.easting)}
                      </td>

                      <td className="num" data-label="Northing">
                        {formatCoordinate(loca.northing)}
                      </td>

                      <td data-label="Latitude">
                        {loca.latitude || "—"}
                      </td>

                      <td data-label="Longitude">
                        {loca.longitude || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {addingLoca && (
        <AddLocaModal
          projectId={projectId}
          onClose={() => onAddingLocaChange(false)}
          onCreated={onLocaCreated}
        />
      )}
    </section>
  );
}
