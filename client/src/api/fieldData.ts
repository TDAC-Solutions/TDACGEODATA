import { apiClient } from "./apiClient";

// ---------------------------------------------------------------------------
// Borehole / Drilling
// ---------------------------------------------------------------------------

export interface BoreholeRecord {
  depth_from: number;
  depth_to: number | null;
  soil_description: string | null;
  sand_clay: string | null;
  avg_n_value: number | null;
  created_by?: string | null;
  created_at?: string | null;
}

export interface BoreholeUpdate {
  depth_from: number;
  depth_to: number | null;
  soil_description: string | null;
  sand_clay: string | null;
}

export interface BoreholeCreate {
  depth_from: number;
  depth_to: number | null;
  soil_description: string | null;
  sand_clay: string | null;
}

export async function getBoreholeRecords(
  projectId: string,
  locaId: string
): Promise<BoreholeRecord[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/borehole`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load borehole data: ${response.status}`
    );
  }

  const result = await response.json();
  return result.records;
}

export async function updateBoreholeRecord(
  projectId: string,
  locaId: string,
  originalDepthFrom: number,
  data: BoreholeUpdate
): Promise<BoreholeRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/borehole/${encodeURIComponent(originalDepthFrom)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to update borehole record: ${response.status}`
    );
  }

  const result = await response.json();
  return result.record;
}

export async function deleteBoreholeRecord(
  projectId: string,
  locaId: string,
  depthFrom: number
): Promise<void> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/borehole/${encodeURIComponent(depthFrom)}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ??
        `Failed to delete borehole record: ${response.status}`
    );
  }
}

export async function createBoreholeRecord(
  projectId: string,
  locaId: string,
  data: BoreholeCreate
): Promise<BoreholeRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/borehole`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to create borehole record: ${response.status}`
    );
  }

  const result = await response.json();
  return result.record;
}

// ---------------------------------------------------------------------------
// SPT
// ---------------------------------------------------------------------------

export interface SptRecord {
  spt_depth: number;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
  n_value: number | null;
  status?: string | null;
  /**
   * Stable record identity. Unlike spt_depth, which an edit can change, this
   * survives a depth correction, so it is what attachments anchor on.
   */
  sample_id?: string | null;
  /** Files already attached to this sample; drives the row badge. */
  attachment_count?: number;
  /** Position in the depth-ordered list. Derived by the server; read-only. */
  list_no: number;
}

export interface SptUpdate {
  spt_depth: number;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
}

// One row of the SPT entry grid. n_value/SPTN is never sent - the
// backend always computes and validates it from the blow counts.
export interface SptRow {
  spt_depth: number | null;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
}

export interface SptPendingRecord {
  sample_id: string;
  spt_depth: number;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
  n_value: number | null;
  status: string;
  created_by: string | null;
  created_at: string | null;
  /** Present when the row is in the queue because of an edit rather than a
      fresh submission; sourced from the latest SAMPLE_EDITED audit event. */
  last_edited_by?: string | null;
  last_edited_at?: string | null;
  /** Position in the pending queue. Derived by the server; read-only. */
  list_no: number;
}

export interface SoilRecord {
  sample_id: string;
  /** Present on the Sample Register, which spans locations. Absent from the
   *  per-location /soil response, where the URL already names the location. */
  loca_id?: string;
  depth_from: number;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
  n_value: number | null;
  created_by?: string | null;
  created_at?: string | null;
}

export async function getSptRecords(
  projectId: string,
  locaId: string
): Promise<SptRecord[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/spt`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load SPT data: ${response.status}`
    );
  }

  const result = await response.json();
  return result.records;
}

export async function updateSptRecord(
  projectId: string,
  locaId: string,
  originalSptDepth: number,
  data: SptUpdate
): Promise<SptRecord> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/spt/${encodeURIComponent(originalSptDepth)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to update SPT record: ${response.status}`
    );
  }

  const result = await response.json();
  return result.record;
}

export async function deleteSptRecord(
  projectId: string,
  locaId: string,
  sptDepth: number
): Promise<void> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/spt/${encodeURIComponent(sptDepth)}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ??
        `Failed to delete SPT record: ${response.status}`
    );
  }
}

export async function submitSptRecords(
  projectId: string,
  locaId: string,
  rows: SptRow[]
): Promise<SptRecord[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/spt/bulk`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records: rows }),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to submit SPT records: ${response.status}`
    );
  }

  const result = await response.json();
  return result.records;
}

export async function getPendingSptRecords(
  projectId: string,
  locaId: string
): Promise<SptPendingRecord[]> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/spt/pending`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load pending SPT records: ${response.status}`
    );
  }

  const result = await response.json();
  return result.records;
}

export async function approveSptRecord(
  projectId: string,
  locaId: string,
  sptDepth: number
): Promise<void> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/spt/${encodeURIComponent(sptDepth)}/approve`,
    { method: "POST" }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to approve SPT record: ${response.status}`
    );
  }
}

export async function rejectSptRecord(
  projectId: string,
  locaId: string,
  sptDepth: number,
  reason: string | null
): Promise<void> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(
      locaId
    )}/field-data/spt/${encodeURIComponent(sptDepth)}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to reject SPT record: ${response.status}`
    );
  }
}

// ---------------------------------------------------------------------------
// Sampling / Coring
// ---------------------------------------------------------------------------

/** Sampling & Coring > Rock is view-only: approved Rock-workflow records. */
export interface SamplingRecord {
  sample_id: string;
  /** Present on the Sample Register; see SoilRecord.loca_id. */
  loca_id?: string;
  depth_from: number;
  depth_to: number | null;
  rock_description: string | null;
  recovery: number | null;
  rqd: number | null;
  remark: string | null;
  lift_no: string | null;
  created_by: string | null;
  created_at: string | null;
}

/* ---------------------------------------------------------------------------
   Sample Register (Lab Data > Sample Register)
   ---------------------------------------------------------------------------
   The approved Soil (SPT) and Rock (coring) register that used to live in
   Field Data > Sampling / Coring. Lab Data is project-scoped, so this fetches
   the whole project in one request and carries loca_id on every row, rather
   than the client calling the per-location endpoints once per borehole.

   `locaId` narrows server-side. Leaving it undefined returns every location,
   and the caller decides whether to show a Location column.
   ------------------------------------------------------------------------- */

export interface SampleRegister {
  soil: SoilRecord[];
  rock: SamplingRecord[];
}

export async function getSampleRegister(
  projectId: string,
  locaId?: string
): Promise<SampleRegister> {
  // Project-scoped, so no /locas/{id} segment: the endpoint sits on the
  // portfolio router, and locaId narrows it as a query parameter.
  const scope = locaId ? `?loca_id=${encodeURIComponent(locaId)}` : "";

  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/sample-register${scope}`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ??
        `Failed to load the sample register: ${response.status}`
    );
  }

  return response.json();
}

export interface GroundwaterResponse {
  available: boolean;
  reason: string | null;
  records: unknown[];
}

export async function getGroundwaterStatus(
  projectId: string,
  locaId: string
): Promise<GroundwaterResponse> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/groundwater`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load groundwater data: ${response.status}`
    );
  }

  return response.json();
}

export interface ProjectSample {
  sample_id: string;
  loca_id: string;
  spec_ref?: string | null;
  depth_from: number;
  depth_to: number | null;
  sample_type?: string | null;
}

export async function getProjectSamples(
  projectId: string
): Promise<ProjectSample[]> {
    const response = await apiClient(
    `/api/portfolio/projects/${projectId}/samples`
  );

  if (!response.ok) {
    throw new Error("Failed to load project samples.");
  }

  const data = await response.json();

  return data.samples;
}

export async function getProjectSampleTests(
  projectId: string
) {
  const response = await apiClient(
    `/api/portfolio/projects/${projectId}/sample-tests`
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.detail || "Failed to load sample test information."
    );
  }

  return data.samples;
}

export async function createProjectLabTest(
  projectId: string,
  payload: {
    loca_id: string;
    samp_id: string;
    specimen_ref: string;
    test_type: string;
    method_definition_id: string;
    laboratory: string;
    technician?: string;
  }
) {
  const response = await apiClient(
    `/api/portfolio/projects/${projectId}/lab/tests`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.detail || "Failed to create laboratory test."
    );
  }

  return data;
}

export interface LabTestCreatePayload {
  loca_id: string;
  samp_id: string;
  specimen_ref: string;
  test_type: string;
  method_definition_id: string;
  laboratory: string;
  technician?: string;
}

export interface LabTestBulkResponse {
  message: string;
  tests: Array<{
    test_id: string;
    project_id: string;
    loca_id: string;
    samp_id: string;
    spec_ref: string;
    test_type: string;
    method_definition_id: string;
    laboratory: string;
    technician: string | null;
    status: string;
    current_revision: number;
    row_version: number;
  }>;
}

export class ApiStatusError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiStatusError";
  }
}

export async function createProjectLabTestsBulk(
  projectId: string,
  tests: LabTestCreatePayload[]
): Promise<LabTestBulkResponse> {
  const response = await apiClient(
    `/api/portfolio/projects/${projectId}/lab/tests/bulk`,
    {
      method: "POST",
      body: JSON.stringify({ tests }),
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new ApiStatusError(
      data.detail || "Failed to create laboratory tests.",
      response.status
    );
  }

  return data;
}

/* getProjectLabTests used to be defined here as well as in api/lab.ts, with
 * the same URL and two different return types -- this one returned `any`, so
 * OverviewTab got no type checking on a payload its siblings did. The typed
 * copy in api/lab.ts is the one that survives. */

// ---------------------------------------------------------------------------
// Admin audit (Field Data -> Overview). Admin only - enforced by the backend.
// ---------------------------------------------------------------------------

export interface AuditChange {
  field: string | null;
  old_value: unknown;
  new_value: unknown;
  edited_by: string;
  edited_at: string | null;
}

export interface AuditWorkflowEvent {
  action: string;
  by: string;
  at: string | null;
  detail: string | null;
}

export interface AuditHistory {
  sample_id?: string;
  source?: "SPT" | "CORE";
  entry: Record<string, unknown>;
  created_by: string | null;
  created_at: string | null;
  last_edited_by: string | null;
  last_edited_at: string | null;
  changes: AuditChange[];
  events: AuditWorkflowEvent[];
}

export interface AuditBoreholeEntry {
  depth_from: number;
  depth_to: number | null;
  soil_description: string | null;
  sand_clay: string | null;
  created_by: string | null;
  created_at: string | null;
}

export interface AuditSampleEntry {
  sample_id: string;
  source: "SPT" | "CORE" | "ROCK";
  depth_from: number;
  status: string | null;
  created_by: string | null;
  created_at: string | null;
}

async function auditGet<T>(
  projectId: string,
  locaId: string,
  path: string
): Promise<T> {
  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/locas/${encodeURIComponent(locaId)}/field-data/audit/${path}`
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load audit data: ${response.status}`
    );
  }

  return response.json();
}

export async function getAuditBoreholeEntries(
  projectId: string,
  locaId: string
): Promise<AuditBoreholeEntry[]> {
  const result = await auditGet<{ entries: AuditBoreholeEntry[] }>(
    projectId,
    locaId,
    "borehole"
  );
  // An unexpected 200 body leaves this undefined, and every caller reads
  // .length on it, turning a response surprise into a blank-panel crash.
  return result.entries ?? [];
}

export function getAuditBoreholeHistory(
  projectId: string,
  locaId: string,
  depthFrom: number
): Promise<AuditHistory> {
  return auditGet<AuditHistory>(
    projectId,
    locaId,
    `borehole/${encodeURIComponent(depthFrom)}`
  );
}

export async function getAuditSampleEntries(
  projectId: string,
  locaId: string
): Promise<AuditSampleEntry[]> {
  const result = await auditGet<{ entries: AuditSampleEntry[] }>(
    projectId,
    locaId,
    "samples"
  );
  // An unexpected 200 body leaves this undefined, and every caller reads
  // .length on it, turning a response surprise into a blank-panel crash.
  return result.entries ?? [];
}

export function getAuditSampleHistory(
  projectId: string,
  locaId: string,
  sampleId: string
): Promise<AuditHistory> {
  return auditGet<AuditHistory>(
    projectId,
    locaId,
    `samples/${encodeURIComponent(sampleId)}`
  );
}

// ---------------------------------------------------------------------------
// Rock (Field Data > Rock) - same workflow as SPT
// ---------------------------------------------------------------------------

export interface RockRecord {
  sample_id: string;
  depth_from: number;
  depth_to: number;
  /** Server-derived from `pieces`; never sent by the client. */
  recovery: number | null;
  rqd: number | null;
  rock_type: string | null;
  lift_no: string | null;
  /** One entry per Block Number, in entry order, always in centimetres. */
  pieces: number[];
  status: string;
  created_by: string | null;
  created_at: string | null;
  /** Position in the depth-ordered list. Derived by the server; read-only. */
  list_no: number;
}

/** What the Block Number boxes are typed in. Centimetres is the default. */
export type PieceUnit = "cm" | "m";

/** One Rock run, for both new submissions and edits. */
export interface RockRow {
  depth_from: number;
  depth_to: number;
  rock_type: string;
  lift_no: string | null;
  /** Individual piece lengths, in entry order. */
  pieces: number[];
  piece_unit: PieceUnit;
}

export interface RockPendingRecord {
  sample_id: string;
  depth_from: number;
  depth_to: number;
  recovery: number | null;
  rqd: number | null;
  rock_type: string | null;
  lift_no: string | null;
  pieces: number[];
  status: string;
  created_by: string | null;
  created_at: string | null;
  last_edited_by?: string | null;
  last_edited_at?: string | null;
  /** Position in the pending queue. Derived by the server; read-only. */
  list_no: number;
}

function rockBase(projectId: string, locaId: string): string {
  return `/api/portfolio/projects/${encodeURIComponent(
    projectId
  )}/locas/${encodeURIComponent(locaId)}/field-data/rock`;
}

async function rockFail(response: Response, what: string): Promise<never> {
  const errorBody = await response.json().catch(() => null);
  const detail = errorBody?.detail;
  // FastAPI validation errors arrive as a list of {msg}; show them readably.
  const message = Array.isArray(detail)
    ? detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
    : detail;
  throw new Error(message || `Failed to ${what}: ${response.status}`);
}

export async function getRockRecords(
  projectId: string,
  locaId: string
): Promise<RockRecord[]> {
  const response = await apiClient(rockBase(projectId, locaId));
  if (!response.ok) await rockFail(response, "load Rock data");
  const result = await response.json();
  return result.records;
}

export async function submitRockRecords(
  projectId: string,
  locaId: string,
  rows: RockRow[]
): Promise<RockRecord[]> {
  const response = await apiClient(`${rockBase(projectId, locaId)}/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ records: rows }),
  });
  if (!response.ok) await rockFail(response, "submit Rock records");
  const result = await response.json();
  return result.records;
}

export async function updateRockRecord(
  projectId: string,
  locaId: string,
  originalDepthFrom: number,
  data: RockRow
): Promise<void> {
  const response = await apiClient(
    `${rockBase(projectId, locaId)}/${encodeURIComponent(originalDepthFrom)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data),
    }
  );
  if (!response.ok) await rockFail(response, "update Rock record");
}

export async function deleteRockRecord(
  projectId: string,
  locaId: string,
  depthFrom: number
): Promise<void> {
  const response = await apiClient(
    `${rockBase(projectId, locaId)}/${encodeURIComponent(depthFrom)}`,
    { method: "DELETE" }
  );
  if (!response.ok) await rockFail(response, "delete Rock record");
}

export async function getPendingRockRecords(
  projectId: string,
  locaId: string
): Promise<RockPendingRecord[]> {
  const response = await apiClient(`${rockBase(projectId, locaId)}/pending`);
  if (!response.ok) await rockFail(response, "load pending Rock records");
  const result = await response.json();
  return result.records;
}

export async function approveRockRecord(
  projectId: string,
  locaId: string,
  depthFrom: number
): Promise<void> {
  const response = await apiClient(
    `${rockBase(projectId, locaId)}/${encodeURIComponent(depthFrom)}/approve`,
    { method: "POST" }
  );
  if (!response.ok) await rockFail(response, "approve Rock record");
}

export async function rejectRockRecord(
  projectId: string,
  locaId: string,
  depthFrom: number,
  reason: string | null
): Promise<void> {
  const response = await apiClient(
    `${rockBase(projectId, locaId)}/${encodeURIComponent(depthFrom)}/reject`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason }),
    }
  );
  if (!response.ok) await rockFail(response, "reject Rock record");
}
