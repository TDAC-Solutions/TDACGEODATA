import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  createProject,
  getNextProjectId,
  type CreateProjectPayload,
} from "../api/portfolio";

export function CreateProjectPage() {
  const navigate = useNavigate();

  const [form, setForm] = useState({
    project_id: "",
    project_name: "",
    project_location: "",
    project_client: "",
    consultant_name:"",
    contractor_name:"",
    project_type: "",

    road_reference: "",
    chainage_text: "",
    structure_reference: "",
    selected_boreholes: "",

    report_type: "",
    report_title: "",
    report_volume_title: "",
    document_reference: "",
    revision: "",
    report_date: "",
    issue_status: "",

    tdac_company_name:
      "TDAC Geotechnical Solutions Private Limited",
    groundwater_basis: "",

    design_standard_basis: "",
    factor_of_safety_basis: "",
    load_combination_basis: "",
    construction_verification_requirement: "",
    pile_load_test_requirement: "",
  });

  const [projectIdMode, setProjectIdMode] = useState<
    "automatic" | "manual"
  >("automatic");

  const [projectIdLoading, setProjectIdLoading] =
    useState(false);
    useEffect(() => {
      handleProjectIdModeChange("automatic");
    }, []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  function handleChange(
    e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>
  ) {
    const { name, value } = e.target;

    setForm((current) => ({
      ...current,
      [name]: value,
    }));
  }

  async function handleProjectIdModeChange(
    mode: "automatic" | "manual"
  ) {
    setProjectIdMode(mode);
    setError("");

    if (mode === "automatic") {
      try {
        setProjectIdLoading(true);

        const nextId = await getNextProjectId();

        setForm((current) => ({
          ...current,
          project_id: nextId,
        }));
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Unable to generate project ID."
        );
      } finally {
        setProjectIdLoading(false);
      }
    } else {
      setForm((current) => ({
        ...current,
        project_id: "",
      }));
    }
  }

  async function handleSubmit(
    e: React.FormEvent<HTMLFormElement>
  ) {
    e.preventDefault();
    setError("");

    if (!form.project_id.trim()) {
      setError("Project ID is required.");
      return;
    }

    if (!form.project_name.trim()) {
      setError("Project title is required.");
      return;
    }

    if (!form.project_client.trim()) {
      setError("Client name is required.");
      return;
    }

    if (!form.project_location.trim()) {
      setError("Site location is required.");
      return;
    }

    if (!form.consultant_name.trim()) {
      setError("Consultant name is required.");
      return;
    }

    if (!form.contractor_name.trim()) {
      setError("Contractor name is required.");
      return;
    }

    if (!form.road_reference.trim()) {
      setError("Road / highway reference is required.");
      return;
    }

    if (!form.chainage_text.trim()) {
      setError("Chainage / chainage range is required.");
      return;
    }

    if (!form.structure_reference.trim()) {
      setError("Structure / location reference is required.");
      return;
    }

    if (!form.selected_boreholes.trim()) {
      setError("Selected borehole IDs are required.");
      return;
    }

    if (!form.report_type) {
      setError("Report type is required.");
      return;
    }

    if (!form.report_title.trim()) {
      setError("Report title is required.");
      return;
    }

    if (!form.report_volume_title.trim()) {
      setError("Report volume title is required.");
      return;
    }

    if (!form.document_reference.trim()) {
      setError("TDAC document reference is required.");
      return;
    }

    if (!form.revision.trim()) {
      setError("Revision is required.");
      return;
    }

    if (!form.report_date) {
      setError("Report date is required.");
      return;
    }

    if (!form.issue_status) {
      setError("Issue status is required.");
      return;
    }

    if (!form.tdac_company_name.trim()) {
      setError("TDAC company name is required.");
      return;
    }

    if (!form.groundwater_basis.trim()) {
      setError("Groundwater basis is required.");
      return;
    }

    if (form.report_type === "Design") {
      if (!form.design_standard_basis.trim()) {
        setError("Design standard basis is required for Design reports.");
        return;
      }

      if (!form.factor_of_safety_basis.trim()) {
        setError(
          "Factor of safety basis is required for Design reports."
        );
        return;
      }

      if (!form.load_combination_basis.trim()) {
        setError(
          "Load combination basis is required for Design reports."
        );
        return;
      }

      if (!form.construction_verification_requirement.trim()) {
        setError(
          "Construction verification requirement is required for Design reports."
        );
        return;
      }

      if (!form.pile_load_test_requirement.trim()) {
        setError(
          "Pile load test requirement is required for Design reports."
        );
        return;
      }
    }

    setLoading(true);

    try {
      const data: CreateProjectPayload = {
        project_id: projectIdMode === "automatic"? "AUTO": form.project_id.trim(),
        project_name: form.project_name.trim(),
        project_location: form.project_location.trim(),
        project_client: form.project_client.trim(),
        consultant_name: form.consultant_name.trim(),
        contractor_name: form.contractor_name.trim(),

        metadata: {
          road_reference:
            form.road_reference.trim() || null,
          chainage_text:
            form.chainage_text.trim() || null,
          structure_reference:
            form.structure_reference.trim() || null,
          selected_boreholes:
            form.selected_boreholes.trim() || null,
          project_type: form.project_type || null,
          report_type: form.report_type || null,
          
          report_title:
            form.report_title.trim() || null,
          report_volume_title:
            form.report_volume_title.trim() || null,
          document_reference:
            form.document_reference.trim() || null,
          revision:
            form.revision.trim() || null,
          report_date:
            form.report_date || null,
          issue_status:
            form.issue_status || null,

          tdac_company_name:
            form.tdac_company_name.trim() || null,
          groundwater_basis:
            form.groundwater_basis.trim() || null,

          design_standard_basis:
            form.design_standard_basis.trim() || null,
          factor_of_safety_basis:
            form.factor_of_safety_basis.trim() || null,
          load_combination_basis:
            form.load_combination_basis.trim() || null,
          construction_verification_requirement:
            form.construction_verification_requirement.trim() || null,
          pile_load_test_requirement:
            form.pile_load_test_requirement.trim() || null,
        },
      };

      await createProject(data);

      navigate("/");
    } catch (err) {
      console.error("Failed to create project:", err);

      setError(
        err instanceof Error
          ? err.message
          : "Unable to create project."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">
            Add New Project
          </h1>

          <p className="page-sub">
            Create a new project and its document-control metadata.
          </p>
        </div>

        <div className="page-head-actions">
          <button
            type="button"
            className="btn"
            onClick={() => navigate("/")}
            disabled={loading}
          >
            Cancel
          </button>
        </div>
      </div>

      {error && (
        <div className="warning-note">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {/* =====================================================
            PROJECT DETAILS
        ====================================================== */}
        <div className="panel">
          <div className="panel-head">
            <h2 className="panel-title">
              Project Details
            </h2>
          </div>

          <div className="panel-body">
            <div className="grid grid-2">

              {/* Project ID */}
              <div className="form-field">
                <label htmlFor="project_id">
                  Project ID
                </label>

                <select
                  value={projectIdMode}
                  onChange={(e) =>
                    handleProjectIdModeChange(
                      e.target.value as
                        | "automatic"
                        | "manual"
                    )
                  }
                  disabled={loading || projectIdLoading}
                >
                  <option value="automatic">
                    Automatic
                  </option>
                  <option value="manual">
                    Manual
                  </option>
                </select>

                <input
                  id="project_id"
                  name="project_id"
                  type="text"
                  value={form.project_id}
                  onChange={handleChange}
                  disabled={
                    projectIdMode === "automatic" ||
                    projectIdLoading ||
                    loading
                  }
                  placeholder={
                    projectIdMode === "automatic"
                      ? "Generating..."
                      : "e.g. 102 or TDAC-2025-12-123"
                  }
                  required
                />
              </div>

              {/* Project Title */}
              <div className="form-field">
                <label htmlFor="project_name">
                  Project Title
                </label>

                <input
                  id="project_name"
                  name="project_name"
                  type="text"
                  value={form.project_name}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Project Type */}
              <div className="form-field">
                <label htmlFor="project_type">
                  Project Type
                </label>

                <select
                  id="project_type"
                  name="project_type"
                  value={form.project_type}
                  onChange={handleChange}
                  required
                >
                  <option value="">
                    Select project type
                  </option>

                  <option value="LAB_ONLY">
                    Lab Only
                  </option>

                  <option value="REPORT_ONLY">
                    Report Only
                  </option>

                  <option value="LAB_AND_REPORT">
                    Lab + Report
                  </option>
                </select>
              </div>

              {/* Site Location */}
              <div className="form-field">
                <label htmlFor="project_location">
                  Site Location
                </label>

                <input
                  id="project_location"
                  name="project_location"
                  type="text"
                  value={form.project_location}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Client Name */}
              <div className="form-field">
                <label htmlFor="project_client">
                  Client Name
                </label>

                <input
                  id="project_client"
                  name="project_client"
                  type="text"
                  value={form.project_client}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Road Reference */}
              <div className="form-field">
                <label htmlFor="road_reference">
                  Road / Highway Reference
                </label>

                <input
                  id="road_reference"
                  name="road_reference"
                  type="text"
                  value={form.road_reference}
                  onChange={handleChange}
                  placeholder="e.g. NH-66"
                  required
                />
              </div>

              {/* Chainage */}
              <div className="form-field">
                <label htmlFor="chainage_text">
                  Chainage / Chainage Range
                </label>

                <input
                  id="chainage_text"
                  name="chainage_text"
                  type="text"
                  value={form.chainage_text}
                  onChange={handleChange}
                  placeholder="e.g. CH 397+750 to CH 423+780"
                  required
                />
              </div>

              {/* Structure Reference */}
              <div className="form-field">
                <label htmlFor="structure_reference">
                  Structure / Location Reference
                </label>

                <input
                  id="structure_reference"
                  name="structure_reference"
                  type="text"
                  value={form.structure_reference}
                  onChange={handleChange}
                  placeholder="e.g. VUP, ROB, retaining wall"
                  required
                />
              </div>

              {/* Selected Boreholes */}
              <div className="form-field">
                <label htmlFor="selected_boreholes">
                  Selected Borehole IDs
                </label>

                <input
                  id="selected_boreholes"
                  name="selected_boreholes"
                  type="text"
                  value={form.selected_boreholes}
                  onChange={handleChange}
                  placeholder="e.g. BH-01, BH-02"
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="consultant_name">
                  Consultant Name
                </label>

                <input
                  id="consultant_name"
                  name="consultant_name"
                  type="text"
                  value={form.consultant_name}
                  onChange={handleChange}
                  required
                />
              </div>

              <div className="form-field">
                <label htmlFor="contractor_name">
                  Contractor Name
                </label>

                <input
                  id="contractor_name"
                  name="contractor_name"
                  type="text"
                  value={form.contractor_name}
                  onChange={handleChange}
                  required
                />
              </div>
            </div>
          </div>
        </div>

        {/* =====================================================
            REPORT / DOCUMENT CONTROL
        ====================================================== */}
        <div
          className="panel"
          style={{ marginTop: "13px" }}
        >
          <div className="panel-head">
            <h2 className="panel-title">
              Report &amp; Document Control
            </h2>
          </div>

          <div className="panel-body">
            <div className="grid grid-2">

              {/* Report Type */}
              <div className="form-field">
                <label htmlFor="report_type">
                  Report Type
                </label>

                <select
                  id="report_type"
                  name="report_type"
                  value={form.report_type}
                  onChange={handleChange}
                  required
                >
                  <option value="">
                    Select report type
                  </option>
                  <option value="Factual">
                    Factual
                  </option>
                  <option value="Interpretive">
                    Interpretive
                  </option>
                  <option value="Design">
                    Design
                  </option>
                  <option value="Final">
                    Final
                  </option>
                </select>
              </div>

              {/* Report Title */}
              <div className="form-field">
                <label htmlFor="report_title">
                  Report Title
                </label>

                <input
                  id="report_title"
                  name="report_title"
                  type="text"
                  value={form.report_title}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Report Volume Title */}
              <div className="form-field">
                <label htmlFor="report_volume_title">
                  Report Volume Title
                </label>

                <input
                  id="report_volume_title"
                  name="report_volume_title"
                  type="text"
                  value={form.report_volume_title}
                  onChange={handleChange}
                  placeholder="e.g. Volume I – Geotechnical Investigation Factual Data"
                  required
                />
              </div>

              {/* Document Reference */}
              <div className="form-field">
                <label htmlFor="document_reference">
                  TDAC Document Reference
                </label>

                <input
                  id="document_reference"
                  name="document_reference"
                  type="text"
                  value={form.document_reference}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Revision */}
              <div className="form-field">
                <label htmlFor="revision">
                  Revision
                </label>

                <input
                  id="revision"
                  name="revision"
                  type="text"
                  value={form.revision}
                  onChange={handleChange}
                  placeholder="e.g. R0, A0, B1"
                  required
                />
              </div>

              {/* Report Date */}
              <div className="form-field">
                <label htmlFor="report_date">
                  Report Date
                </label>

                <input
                  id="report_date"
                  name="report_date"
                  type="date"
                  value={form.report_date}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Issue Status */}
              <div className="form-field">
                <label htmlFor="issue_status">
                  Issue Status
                </label>

                <select
                  id="issue_status"
                  name="issue_status"
                  value={form.issue_status}
                  onChange={handleChange}
                  required
                >
                  <option value="">
                    Select issue status
                  </option>
                  <option value="Draft">
                    Draft
                  </option>
                  <option value="For Review">
                    For Review
                  </option>
                  <option value="Client Issue">
                    Client Issue
                  </option>
                  <option value="Final">
                    Final
                  </option>
                  <option value="Superseded">
                    Superseded
                  </option>
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* =====================================================
            TDAC / FACTUAL DATA
        ====================================================== */}
        <div
          className="panel"
          style={{ marginTop: "13px" }}
        >
          <div className="panel-head">
            <h2 className="panel-title">
              TDAC &amp; Factual Data
            </h2>
          </div>

          <div className="panel-body">
            <div className="grid grid-2">

              {/* TDAC Company */}
              <div className="form-field">
                <label htmlFor="tdac_company_name">
                  TDAC Company Name
                </label>

                <input
                  id="tdac_company_name"
                  name="tdac_company_name"
                  type="text"
                  value={form.tdac_company_name}
                  onChange={handleChange}
                  required
                />
              </div>

              {/* Groundwater Basis */}
              <div className="form-field">
                <label htmlFor="groundwater_basis">
                  Groundwater Basis
                </label>

                <textarea
                  id="groundwater_basis"
                  name="groundwater_basis"
                  value={form.groundwater_basis}
                  onChange={handleChange}
                  rows={3}
                  placeholder="e.g. Borehole-recorded groundwater level"
                  required
                />
              </div>
            </div>
          </div>
        </div>

        {/* =====================================================
            DESIGN BASIS
        ====================================================== */}
        <div
          className="panel"
          style={{ marginTop: "13px" }}
        >
          <div className="panel-head">
            <h2 className="panel-title">
              Design Basis
            </h2>
          </div>

          <div className="panel-body">
            <p className="page-sub">
              Required when Report Type is Design.
            </p>

            <div className="grid grid-2">

              {/* Design Standard */}
              <div className="form-field">
                <label htmlFor="design_standard_basis">
                  Design Standard Basis
                </label>

                <textarea
                  id="design_standard_basis"
                  name="design_standard_basis"
                  value={form.design_standard_basis}
                  onChange={handleChange}
                  rows={3}
                  placeholder="e.g. IRC / IS / project design basis"
                  required={form.report_type === "Design"}
                />
              </div>

              {/* Factor of Safety */}
              <div className="form-field">
                <label htmlFor="factor_of_safety_basis">
                  Factor of Safety Basis
                </label>

                <textarea
                  id="factor_of_safety_basis"
                  name="factor_of_safety_basis"
                  value={form.factor_of_safety_basis}
                  onChange={handleChange}
                  rows={3}
                  required={form.report_type === "Design"}
                />
              </div>

              {/* Load Combination */}
              <div className="form-field">
                <label htmlFor="load_combination_basis">
                  Load Combination Basis
                </label>

                <textarea
                  id="load_combination_basis"
                  name="load_combination_basis"
                  value={form.load_combination_basis}
                  onChange={handleChange}
                  rows={3}
                  placeholder="e.g. Service / working / ultimate"
                  required={form.report_type === "Design"}
                />
              </div>

              {/* Construction Verification */}
              <div className="form-field">
                <label htmlFor="construction_verification_requirement">
                  Construction Verification Requirement
                </label>

                <textarea
                  id="construction_verification_requirement"
                  name="construction_verification_requirement"
                  value={form.construction_verification_requirement}
                  onChange={handleChange}
                  rows={3}
                  required={form.report_type === "Design"}
                />
              </div>

              {/* Pile Load Test */}
              <div className="form-field">
                <label htmlFor="pile_load_test_requirement">
                  Pile Load Test Requirement
                </label>

                <textarea
                  id="pile_load_test_requirement"
                  name="pile_load_test_requirement"
                  value={form.pile_load_test_requirement}
                  onChange={handleChange}
                  rows={3}
                  required={form.report_type === "Design"}
                />
              </div>
            </div>
          </div>
        </div>

        {/* =====================================================
            ACTIONS
        ====================================================== */}
        <div
          className="actions"
          style={{
            justifyContent: "flex-end",
            marginTop: "13px",
          }}
        >
          <button
            type="button"
            className="btn"
            onClick={() => navigate("/")}
            disabled={loading}
          >
            Cancel
          </button>

          <button
            type="submit"
            className="btn btn-primary"
            disabled={
              loading ||
              projectIdLoading ||
              !form.project_id
            }
          >
            {loading
              ? "Creating..."
              : "Create Project"}
          </button>
        </div>
      </form>
    </>
  );
}