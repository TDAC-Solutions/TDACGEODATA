import { apiClient } from "../api/apiClient";
import type {
  FieldTableDataset,
  FieldTableImportResult,
  FieldTableRow,
  ImportedWorkbook,
  ProjectImportMetadata,
  ParsedWorkbookResponse,
  SpreadsheetProfile,
} from "./contracts";

export type {
  FieldTableDataset,
  FieldTableImportResult,
  FieldTableRow,
  ImportedWorkbook,
  ImportSuggestions,
  ProjectImportMetadata,
  ParsedWorkbookResponse,
  SpreadsheetProfile,
} from "./contracts";

/**
 * Field-profile spreadsheet API.
 *
 * The existing /api/excel/workbook endpoint is retained as a compatibility
 * adapter while the package is reorganized. The profile layer is the
 * reusable client entry point for new import screens.
 */

export async function parseExcelWorkbook(
  file: File
): Promise<ParsedWorkbookResponse> {
  const body = new FormData();
  body.append("file", file);

  const response = await apiClient("/api/excel/workbook", {
    method: "POST",
    body,
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? "Unable to read this spreadsheet."
    );
  }

  return response.json();
}

export async function parseSpreadsheet(
  file: File,
  profile: SpreadsheetProfile = "field"
): Promise<ParsedWorkbookResponse> {
  if (profile === "field") {
    return parseExcelWorkbook(file);
  }

  throw new Error("Unsupported spreadsheet import profile.");
}

export interface ProjectExcelImportPayload {
  project_id: string;
  project_name: string;
  project_location?: string | null;
  project_client?: string | null;
  consultant_name?: string | null;
  contractor_name?: string | null;
  borehole_id?: string | null;
  borehole_type: string;
  start_date?: string | null;
  end_date?: string | null;
  final_depth?: number | null;
  metadata?: ProjectImportMetadata | null;
  workbook: ImportedWorkbook;
}

export interface ImportResult {
  message: string;
  project_id: string;
  borehole_id: string;
  geol_rows: number;
  core_rows: number;
  spt_rows: number;
}

export async function createProjectFromExcel(
  payload: ProjectExcelImportPayload
): Promise<ImportResult> {
  const response = await apiClient("/api/excel/projects", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? "Unable to import this spreadsheet."
    );
  }

  return response.json();
}

export async function createLocaFromExcel(
  projectId: string,
  payload: { borehole_type: string; workbook: ImportedWorkbook }
): Promise<ImportResult> {
  const response = await apiClient(
    `/api/excel/projects/${encodeURIComponent(projectId)}/locas`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? "Unable to import this spreadsheet."
    );
  }

  return response.json();
}

export async function importFieldTable(
  projectId: string,
  locaId: string,
  dataset: FieldTableDataset,
  rows: FieldTableRow[]
): Promise<FieldTableImportResult> {
  const response = await apiClient(
    `/api/excel/projects/${encodeURIComponent(projectId)}/locas/${encodeURIComponent(locaId)}/field-table`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ dataset, rows }),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? "Unable to import this field table."
    );
  }

  return response.json();
}
