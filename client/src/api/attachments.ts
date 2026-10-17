/**
 * Attachment API client.
 *
 * Files live in SharePoint; this module only ever moves metadata and the
 * uploaded bytes. apiClient returns a raw Response (it handles the bearer
 * token and 401 refresh), so each call checks ok and parses explicitly.
 */

import { apiClient } from "./apiClient";

export type AttachmentKind = "image" | "video" | "preview";

export interface Attachment {
  id: number;
  project_id: string;
  /** 'project' files sit at the project root; 'sample' files under samples/. */
  entity_kind: "project" | "sample";
  /** Set only when entity_kind is 'sample'. */
  sample_id: string | null;
  filename: string;
  content_type: string | null;
  size_bytes: number | null;
  /** Picks the renderer: img, video, or iframe. */
  kind: AttachmentKind;
  sharepoint_item_id: string;
  web_url: string;
  preview_url: string | null;
  /**
   * Graph cannot preview every format (Office documents among them). When
   * false the UI falls back to web_url rather than showing a broken frame.
   */
  preview_supported: boolean;
  uploaded_by: number | null;
  uploaded_by_username: string | null;
  uploaded_at: string;
}

export interface SharePointHealth {
  configured: boolean;
}

/** Server errors carry a useful detail string; surface it, not just the code. */
async function errorDetail(response: Response, fallback: string): Promise<Error> {
  try {
    const body = await response.json();
    if (body?.detail) return new Error(String(body.detail));
  } catch {
    // Body was not JSON; fall through to the generic message.
  }
  return new Error(`${fallback} (HTTP ${response.status})`);
}

/**
 * Pull the attachment list out of a response.
 *
 * Guards the shape rather than trusting it. A `.map` over a non-array
 * throws during render, and there is no error boundary above the panel, so
 * one unexpected payload unmounts the entire app and the user sees a blank
 * page rather than an empty gallery. Anything that is not an array is
 * treated as no files, which the panel already renders sensibly.
 */
function readAttachments(body: unknown): Attachment[] {
  return Array.isArray((body as { attachments?: unknown })?.attachments)
    ? (body as { attachments: Attachment[] }).attachments
    : [];
}

export async function fetchAttachments(
  projectId: string,
): Promise<Attachment[]> {
  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}`,
  );

  if (!response.ok) {
    throw await errorDetail(response, "Failed to load attachments");
  }

  const body = await response.json();
  return readAttachments(body);
}

/** Whether SharePoint is configured, so the UI can explain itself. */
export async function fetchSharePointHealth(): Promise<SharePointHealth> {
  const response = await apiClient("/api/attachments/health");

  if (!response.ok) {
    // An unreachable health endpoint must not block the panel; report
    // "not configured" so the user sees the setup hint instead of a crash.
    return { configured: false };
  }

  return response.json();
}

export async function uploadAttachment(
  projectId: string,
  file: File,
): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);

  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}`,
    { method: "POST", body: form },
  );

  if (!response.ok) {
    throw await errorDetail(response, "Upload failed");
  }

  return response.json();
}

/** Mint a fresh preview URL; Graph's expire in about an hour. */
export async function refreshAttachmentPreview(
  projectId: string,
  attachmentId: number,
): Promise<Pick<Attachment, "preview_url" | "preview_supported">> {
  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}/${attachmentId}/refresh-preview`,
    { method: "POST" },
  );

  if (!response.ok) {
    throw await errorDetail(response, "Could not refresh the preview");
  }

  return response.json();
}

/** Files attached to one sample, newest first. */
export async function fetchSampleAttachments(
  projectId: string,
  sampleId: string,
): Promise<Attachment[]> {
  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}/samples/${encodeURIComponent(sampleId)}`,
  );

  if (!response.ok) {
    throw await errorDetail(response, "Failed to load attachments");
  }

  const body = await response.json();
  return readAttachments(body);
}

/** Upload a file against one sample. */
export async function uploadSampleAttachment(
  projectId: string,
  sampleId: string,
  file: File,
): Promise<Attachment> {
  const form = new FormData();
  form.append("file", file);

  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}/samples/${encodeURIComponent(sampleId)}`,
    { method: "POST", body: form },
  );

  if (!response.ok) {
    throw await errorDetail(response, "Upload failed");
  }

  return response.json();
}

export async function refreshSamplePreview(
  projectId: string,
  sampleId: string,
  attachmentId: number,
): Promise<Pick<Attachment, "preview_url" | "preview_supported">> {
  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}/samples/${encodeURIComponent(sampleId)}/${attachmentId}/refresh-preview`,
    { method: "POST" },
  );

  if (!response.ok) {
    throw await errorDetail(response, "Could not refresh the preview");
  }

  return response.json();
}

/**
 * A short-lived token a media element can use.
 *
 * An <img> or <video> cannot send an Authorization header, so the content
 * URL has to carry credentials some other way. The token is typed `media`
 * on the server, lives for minutes, and grants nothing on its own.
 */
export async function fetchMediaToken(
  projectId: string,
): Promise<string | null> {
  try {
    const response = await apiClient(
      `/api/attachments/${encodeURIComponent(projectId)}/media-token`,
    );
    if (!response.ok) return null;
    const body = await response.json();
    return body.media_token ?? null;
  } catch {
    // Not fatal: without a token the panel shows the SharePoint link
    // instead of inline media, which is better than a broken image icon.
    return null;
  }
}

export async function deleteAttachment(
  projectId: string,
  attachmentId: number,
): Promise<void> {
  const response = await apiClient(
    `/api/attachments/${encodeURIComponent(projectId)}/${attachmentId}`,
    { method: "DELETE" },
  );

  if (!response.ok) {
    throw await errorDetail(response, "Could not remove the attachment");
  }
}
