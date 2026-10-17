import { apiClient } from "./apiClient";
export interface ProjectRecord {
  project_id: string;
  project_name: string;
  project_location: string;
  project_client: string;
  consultant_name: string;
  contractor_name: string;
  project_type: string | null;
}
export async function getProject(projectId: string): Promise<ProjectRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}`
  );

  if (!response.ok) {
    throw new Error(`Failed to load project: ${response.status}`);
  }

  return response.json();
}

export interface ProjectUpdate {
  project_name: string;
  project_location: string;
  project_client: string;
}

export async function updateProject(
  projectId: string,
  data: ProjectUpdate
): Promise<ProjectRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to update project: ${response.status}`);
  }

  const result = await response.json();

  return result.project;
}

export interface LocaRecord {
  loca_id: string;
  loca_type: string;
  final_depth: number | null;
  start_date: string | null;
  end_date: string | null;
  ground_level: number | null;
  easting: number | null;
  northing: number | null;
  latitude: string | null;
  longitude: string | null;
  groundwater_depth: number | null;
  project_id: string;
}

export async function getProjectLocas(
  projectId: string
): Promise<LocaRecord[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}/locas`
  );

  if (!response.ok) {
    throw new Error(`Failed to load LOCAs: ${response.status}`);
  }

  const result = await response.json();

  return result.locas;
}

export interface LocaCreate{
  loca_id: string;
  loca_type: string;
  start_date: string | null;
  end_date: string | null;
  final_depth: number | null;
  ground_level: number | null;
  easting: number | null;
  northing: number | null;
  latitude: string | null;
  longitude: string | null;
  groundwater_depth: number | null;
}

export async function createLoca(
  projectId: string,
  data: LocaCreate
): Promise<LocaRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}/locas`,
    {
      method:"POST",
      headers:{
        "Content-Type":"application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if(!response.ok){
    const errorBody = await response.json().catch(()=> null);
    throw new Error(
      errorBody?.detail ?? `Failed to create location: ${response.status}`
    );
  }

  const result = await response.json();
  return result.loca;
}

export interface ProjectMetadataRecord {
  proj_id: string;

  road_reference: string | null;
  chainage_text: string | null;
  structure_reference: string | null;
  selected_boreholes: string | null;

  report_type: string | null;
  report_title: string | null;
  report_volume_title: string | null;
  document_reference: string | null;
  revision: string | null;
  report_date: string | null;
  issue_status: string | null;

  tdac_company_name: string | null;
  groundwater_basis: string | null;

  design_standard_basis: string | null;
  factor_of_safety_basis: string | null;
  load_combination_basis: string | null;
  construction_verification_requirement: string | null;
  pile_load_test_requirement: string | null;
}

export interface UpdateProjectOverviewPayload {
  project_name: string;
  project_location: string;
  project_client: string;
  consultant_name: string;
  contractor_name: string;

  road_reference: string;
  chainage_text: string;
  structure_reference: string;
  selected_boreholes: string;

  report_type: string;
  report_title: string;
  report_volume_title: string;
  document_reference: string;
  revision: string;
  report_date: string;
  issue_status: string;

  tdac_company_name: string;
  groundwater_basis: string;

  design_standard_basis: string;
  factor_of_safety_basis: string;
  load_combination_basis: string;
  construction_verification_requirement: string;
  pile_load_test_requirement: string;
}

export async function updateProjectOverview(
  projectId: string,
  data: UpdateProjectOverviewPayload
): Promise<ProjectRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}/overview`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        errorBody?.message ||
        `Failed to update project overview (${response.status})`
    );
  }

  return response.json();
}

export async function getProjectMetadata(
  projectId: string
): Promise<ProjectMetadataRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(projectId)}/metadata`,
    {
      method: "GET",
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        errorBody?.message ||
        `Failed to load project metadata (${response.status})`
    );
  }

  return response.json();
}