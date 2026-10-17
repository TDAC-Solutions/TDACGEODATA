import { apiClient } from "./apiClient";

export interface PortfolioProject {
  PROJ_ID: string | number;
  PROJ_NAME: string | null;
  PROJ_LOC: string | null;
  PROJ_CLNT: string | null;
  // From tdac."PROJ_METADATA"; null when a project has no metadata row.
  ISSUE_STATUS: string | null;
}

export interface PortfolioSummary {
  total_projects: number;
  projects: PortfolioProject[];
  /** Per-status tally, keyed by ISSUE_STATUS (or "Unspecified"). */
  status_counts: Record<string, number>;
}

export async function getPortfolioSummary(): Promise<PortfolioSummary> {
  const response = await apiClient("/api/portfolio/summary", {
    method: "GET",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to load portfolio data"
    );
  }

  return response.json();
}

// =====================================================
// CREATE PROJECT
// =====================================================

export interface CreateProjectMetadata {
  road_reference?: string | null;
  chainage_text?: string | null;
  structure_reference?: string | null;
  selected_boreholes?: string | null;

  project_type?: string | null;

  report_type?: string | null;
  report_title?: string | null;
  report_volume_title?: string | null;
  document_reference?: string | null;
  revision?: string | null;
  report_date?: string | null;
  issue_status?: string | null;

  tdac_company_name?: string | null;
  groundwater_basis?: string | null;

  design_standard_basis?: string | null;
  factor_of_safety_basis?: string | null;
  load_combination_basis?: string | null;
  construction_verification_requirement?: string | null;
  pile_load_test_requirement?: string | null;
}

export interface CreateProjectPayload {
  project_id: string;
  project_name: string;
  project_location: string;
  project_client: string;
  consultant_name: string;
  contractor_name: string;

  metadata?: CreateProjectMetadata | null;
}

// The server answers with the row it actually inserted. The caller has to
// navigate with project_number from here, not with the ID typed or previewed
// in the form: in Automatic mode the form shows the next free number, but a
// parallel request can claim it first, so the server's reply is the only
// authoritative ID.
export interface CreateProjectResponse {
  message: string;
  project: {
    project_number: string;
    project_name: string;
    country_region: string;
    client: string;
  };
}

export async function createProject(
  data: CreateProjectPayload
): Promise<CreateProjectResponse> {
  const response = await apiClient("/api/portfolio/projects", {
    method: "POST",

    headers: {
      "Content-Type": "application/json",
    },

    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
      errorBody?.message ||
      `Failed to create project (${response.status})`
    );
  }

  return response.json();
}

export async function getNextProjectId(): Promise<string> {
  const response = await apiClient("/api/portfolio/projects/next-id", {
    method: "GET",
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        errorBody?.message ||
        `Failed to generate project ID (${response.status})`
    );
  }

  const data = await response.json();

  return data.project_id;
}
//
// =====================================================
// PROJECT LOCATIONS
// =====================================================

export interface ProjectLoca {
  PROJ_ID?: string | number;
  LOCA_ID?: string;
  loca_id?: string;

  [key: string]: unknown;
}

export async function getProjectLocas(
  projectId: string
): Promise<ProjectLoca[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas`,
    {
      method: "GET",
    }
  );

  if (!response.ok) {
    const errorBody =
      await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        errorBody?.message ||
        `Failed to load project locations (${response.status})`
    );
  }

  const data = await response.json();

  return data.locas ?? [];
}

// =====================================================
// PROJECT SAMPLES
// =====================================================

export interface ProjectSample {
  PROJ_ID?: string | number;
  LOCA_ID?: string;
  SAMP_ID?: string;

  SAMP_TOP?: number | string;
  SAMP_BASE?: number | string;
  SAMP_REF?: string;
  SAMP_TYPE?: string;

  proj_id?: string | number;
  loca_id?: string;
  samp_id?: string;

  samp_top?: number | string;
  samp_base?: number | string;
  samp_ref?: string;
  samp_type?: string;

  [key: string]: unknown;
}

export async function getProjectSamples(
  projectId: string
): Promise<ProjectSample[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/samples`,
    {
      method: "GET",
    }
  );

  if (!response.ok) {
    const errorBody =
      await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        errorBody?.message ||
        `Failed to load project samples (${response.status})`
    );
  }

  const data = await response.json();

  return data.samples ?? [];
}