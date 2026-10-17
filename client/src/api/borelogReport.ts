/**
 * Borelog report API — Field Data → Overview.
 *
 * Both endpoints read the same database rows through the same layout module on
 * the server, so the preview and the PDF cannot disagree about a value:
 *
 *   fetchBorelogReport()  →  the continuous table (no depth page break)
 *   downloadBorelogPdf()  →  the paginated PDF, 20 m a page, with the rock
 *                            appendix behind it
 *   downloadBorelogDocx() →  the soil-profile narrative, as a Word document
 *
 * Every display value — thickness, test depth, the ">50" rule, column widths —
 * is computed server-side in one place. Nothing here derives a number, so
 * re-deriving one in the client is a bug by construction. This module only
 * moves bytes.
 */

import { apiClient } from "./apiClient";

/** A column of the report. `percent` is its width as a share of the log,
 *  identical to the centimetre widths the PDF lays out at. */
export interface BorelogColumn {
  id: string;
  label: string;
  label_lines: string[];
  percent: number;
  rotated: boolean;
}

/**
 * One row of the continuous depth-ordered stream. Layer rows, SPT rows and the
 * two markers share this shape; `kind` says which is which and the rest stay null.
 *
 * The preview draws from `layers` and `spt` -- projections of this same stream
 * -- rather than from `rows` directly, because the log renders each column from
 * its own kind of record.
 */
export interface BorelogReportRow {
  kind: "layer" | "spt" | "water_table" | "termination";

  depth_from: number | null;
  depth_to: number | null;
  thickness: number | null;
  description: string;
  is_rock: boolean;
  recovery: number | null;
  rqd: number | null;
  remark: string;
  /** Already formatted for display, or "NIL". */
  recovery_text: string;
  rqd_text: string;
  /** The v6 hatch for this layer, e.g. "/". */
  hatch: string;

  spt_depth: number | null;
  spt_depth_text: string;
  /** Where the result is plotted: the base of the 45 cm drive, or the start
   *  depth for a worded test. The PDF plots it here, so the log does too. */
  spt_test_depth: number | null;
  blows_15: number | null;
  blows_30: number | null;
  blows_45: number | null;
  n_value: number | null;
  /** The N-value cell text: "45", ">50", "SPT Rebound". */
  n_text: string;
  /** The annotation beside the plot dot: "", ">50", "RB", "Hard Rock". */
  n_plot_text: string;
  /** Dot position across the plot column, 0..1, saturating at N=40. */
  n_plot_fraction: number | null;

  /** Marker text for water_table and termination rows. */
  label: string;
}

/** A stratum. Rock runs additionally carry recovery and RQD. */
export type BorelogReportLayer = BorelogReportRow;

/** One SPT test. */
export type BorelogReportSpt = BorelogReportRow;

export interface BorelogReportHeader {
  title: string;
  project_type: string;
  project_location: string;
  client_name: string;
  borehole_number: string;
  boring_type: string;
  drilling_start: string;
  drilling_completion: string;
  water_table: number | null;
  water_table_text: string;
  termination_depth: number | null;
}

export interface BorelogReportData {
  project_id: string;
  loca_id: string;
  header: BorelogReportHeader;
  columns: BorelogColumn[];
  /** The whole log as one depth-ordered stream. */
  rows: BorelogReportRow[];
  /** The same content split by kind: what the log's columns are drawn from. */
  layers: BorelogReportLayer[];
  spt: BorelogReportSpt[];
  summary: {
    layer_count: number;
    spt_count: number;
    rock_count: number;
    /** 20 m — the PDF's page split, reported so the UI can say so. */
    max_depth_per_page: number;
    /** How many pages the PDF will have. */
    page_count: number;
  };
  max_depth_per_page: number;
  pdf_page_count: number;
}

function reportBase(projectId: string, locaId: string): string {
  return `/api/portfolio/projects/${encodeURIComponent(
    projectId,
  )}/locas/${encodeURIComponent(locaId)}/borelog-report`;
}

export async function fetchBorelogReport(
  projectId: string,
  locaId: string,
): Promise<BorelogReportData> {
  const response = await apiClient(reportBase(projectId, locaId));

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load the borelog report: ${response.status}`,
    );
  }

  const body = await response.json();

  /*
   * Every field below is read with .length or .reduce by the preview, so a
   * response missing any one of them is a TypeError rather than an error
   * state. Normalise here, once, instead of guarding at each call site.
   */
  return {
    project_id: body?.project_id ?? "",
    loca_id: body?.loca_id ?? "",
    header: body?.header ?? {},
    columns: body?.columns ?? [],
    rows: body?.rows ?? [],
    layers: body?.layers ?? [],
    spt: body?.spt ?? [],
    summary: {
      layer_count: body?.summary?.layer_count ?? 0,
      spt_count: body?.summary?.spt_count ?? 0,
      rock_count: body?.summary?.rock_count ?? 0,
      max_depth_per_page: body?.summary?.max_depth_per_page ?? 20,
      page_count: body?.summary?.page_count ?? 0,
    },
    max_depth_per_page: body?.max_depth_per_page ?? 20,
    pdf_page_count: body?.pdf_page_count ?? 0,
  };
}

/**
 * Generate the PDF and hand it to the browser.
 *
 * The PDF carries the v6 rock-logging appendix behind its own pages whenever
 * the hole has core runs to print, so one download is one document either way.
 *
 * Streams the response straight into an object URL rather than buffering a
 * data URI, and revokes the URL on the next frame — a data URI of a multi-page
 * log can run to megabytes of base64 and would be held until the tab closes.
 */
export async function downloadBorelogPdf(
  projectId: string,
  locaId: string,
): Promise<void> {
  await downloadReport(
    `${reportBase(projectId, locaId)}/pdf`,
    `${projectId}_${locaId}_borelog_report.pdf`,
    "PDF",
  );
}

/**
 * Generate the soil-profile Word document and hand it to the browser.
 *
 * The v6 narrative: every stratum in order with the SPT result(s) falling
 * inside it, then the numbered stratigraphic summary. Same download mechanics
 * as the PDF.
 */
export async function downloadBorelogDocx(
  projectId: string,
  locaId: string,
): Promise<void> {
  await downloadReport(
    `${reportBase(projectId, locaId)}/docx`,
    `${projectId}_${locaId}_soil_profile.docx`,
    "Word document",
  );
}

async function downloadReport(
  endpoint: string,
  filename: string,
  label: string,
): Promise<void> {
  const response = await apiClient(endpoint);

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ??
        `Failed to generate the ${label}: ${response.status}`,
    );
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();

  // Revoking synchronously can race the browser's own fetch of the blob, which
  // reports a net::ERR_FILE_NOT_FOUND for a download that otherwise succeeded.
  // A frame is enough for the click to have been consumed.
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}