import { apiClient } from "./apiClient";

/**
 * Sample Register QR codes.
 *
 * The client never builds a QR payload or draws a QR symbol. The server owns
 * the payload -- so it can never disagree with the register above it -- and
 * emits an SVG data URI that drops straight into an <img>.
 */

export type QrScope = "all" | "soil" | "rock";

export interface QrSample {
  kind: "soil" | "rock";
  sample_id: string;
  loca_id: string;
  depth_from: number | null;
  depth_to: number | null;
  /** The exact string embedded in the QR, shown for verification. */
  payload: string;
  /** `data:image/svg+xml;...` -- ready for `<img src>`. */
  qr_svg_data_url: string;
}

export interface QrSheetResponse {
  project_id: string;
  scope: QrScope;
  loca_id: string | null;
  count: number;
  samples: QrSample[];
}

/**
 * Fetch the QR codes for a project.
 *
 *   scope=all   soil + rock
 *   scope=soil  SPT-derived samples only
 *   scope=rock  Rock records only
 *
 * `locaId` narrows server-side, behind the same project guard the register
 * uses, so the checkbox list can never offer a sample the server would
 * refuse to encode.
 */
export async function fetchSampleQrCodes(
  projectId: string,
  scope: QrScope,
  locaId?: string
): Promise<QrSheetResponse> {
  const params = new URLSearchParams({ scope });
  if (locaId) params.set("loca_id", locaId);

  const response = await apiClient(
    `/api/portfolio/projects/${encodeURIComponent(
      projectId
    )}/sample-register/qr?${params.toString()}`
  );

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.detail ?? `Failed to generate QR codes: ${response.status}`
    );
  }

  return response.json();
}