/* Shared spreadsheet import contracts for the frontend. */

export interface ProjectInfoData {
  project_type: string | null;
  project_location: string | null;
  client_name: string | null;
  borehole_number: string | null;
  project_id: string | null;
  start_date: string | null;
  end_date: string | null;
  final_depth: number | null;
}

export interface BorelogRow {
  depth_from: number;
  depth_to: number;
  soil_description: string | null;
  sand_clay: string | null;
}

export interface RockProfileRow {
  depth_from: number;
  depth_to: number;
  rock_description: string | null;
  recovery: number | null;
  rqd: number | null;
  remark: string | null;
}

export interface SPTImportRow {
  spt_depth: number;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
  n_value: number | null;
}

export interface ImportedWorkbook {
  project_info: ProjectInfoData;
  borelog: BorelogRow[];
  rock_profile: RockProfileRow[];
  spt: SPTImportRow[];
}

export interface ImportSuggestions {
  project_name: string | null;
  project_location: string | null;
  project_client: string | null;
  borehole_id: string | null;
  start_date: string | null;
  end_date: string | null;
  final_depth: number | null;
}

/* Free-text project metadata carried alongside an imported workbook. */
export interface ProjectImportMetadata {
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

export type FieldTableDataset = "borelog" | "rock_profile" | "spt";
export type FieldTableRow = BorelogRow | RockProfileRow | SPTImportRow;

export interface ParsedFieldWorkbookResponse {
  workbook: ImportedWorkbook;
  suggestions: ImportSuggestions;
  source_format: "xlsx" | "xlsm";
  dataset: "field_workbook";
}

export interface ParsedFieldTableResponse {
  workbook: null;
  suggestions: null;
  source_format: "csv";
  dataset: FieldTableDataset;
  rows: FieldTableRow[];
}

export type ParsedWorkbookResponse =
  | ParsedFieldWorkbookResponse
  | ParsedFieldTableResponse;

export interface FieldTableImportResult {
  message: string;
  project_id: string;
  loca_id: string;
  dataset: FieldTableDataset;
  rows: number;
  table: string;
}

export type SpreadsheetProfile = "field";
