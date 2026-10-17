import { useCallback, useEffect, useRef, useState } from "react";

import { API_BASE_URL, IS_HTTPS } from "../../config";
import {
  Attachment,
  deleteAttachment,
  fetchMediaToken,
  fetchAttachments,
  fetchSampleAttachments,
  fetchSharePointHealth,
  refreshAttachmentPreview,
  refreshSamplePreview,
  uploadAttachment,
  uploadSampleAttachment,
} from "../../api/attachments";

/** 250 MB, matching the server cap. */
const MAX_UPLOAD_BYTES = 250 * 1024 * 1024;

function formatSize(bytes: number | null): string {
  if (bytes === null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

/**
 * Render one attachment.
 *
 * Images and video stream straight from the item URL. Everything else
 * depends on Graph's preview: when it exists it is embedded, and when it
 * does not the file is offered as a download rather than sitting in an
 * empty iframe.
 */
function AttachmentView({
  attachment,
  mediaToken,
}: {
  attachment: Attachment;
  mediaToken: string | null;
}) {
  // QuickTime and some MKV files report a video MIME type the browser
  // cannot decode. Without this the element sits empty and the user reads
  // it as a failed upload, so fall through to the SharePoint link.
  const [mediaFailed, setMediaFailed] = useState(false);
  // SharePoint's webUrl and the /preview getUrl are both HTML viewer pages,
  // so an <img> or <video> pointed at either decodes nothing and renders
  // broken. Media is fetched from our own content endpoint, which serves
  // the item's actual bytes and keeps the file behind our auth.
  //
  // A media element cannot send an Authorization header, so the URL carries
  // a short-lived media token instead. It is fetched with apiClient (which
  // can send the header) and only stands in for it: the route still
  // resolves the user and checks the project.
  const contentUrl = mediaToken
    ? `${API_BASE_URL}/api/attachments/${encodeURIComponent(
        attachment.project_id,
      )}/${attachment.id}/content?mt=${encodeURIComponent(mediaToken)}`
    : null;

  if (attachment.kind === "image" && contentUrl && !mediaFailed) {
    return (
      <img
        className="attachment-media"
        src={contentUrl}
        alt={attachment.filename}
        loading="lazy"
        onError={() => setMediaFailed(true)}
      />
    );
  }

  if (attachment.kind === "video" && contentUrl && !mediaFailed) {
    return (
      <video
        className="attachment-media"
        src={contentUrl}
        controls
        preload="metadata"
        onError={() => setMediaFailed(true)}
      />
    );
  }

  if (
    attachment.preview_supported &&
    attachment.preview_url &&
    contentUrl &&
    !mediaFailed
  ) {
    return (
      <iframe
        className="attachment-media attachment-frame"
        src={attachment.preview_url}
        title={attachment.filename}
      />
    );
  }

  // No preview available: an icon and a real link beat a broken frame.
  return (
    <div className="attachment-nopreview">
      <span aria-hidden="true">FILE</span>
      <a href={attachment.web_url} target="_blank" rel="noreferrer">
        Open in SharePoint
      </a>
    </div>
  );
}

/**
 * What the panel is showing. Project files live at the SharePoint project
 * root; sample files live under samples/{sampleId}. One component serves
 * both so the upload rules, rendering and error handling cannot drift.
 */
export type AttachmentsScope =
  | { kind: "project" }
  | { kind: "sample"; sampleId: string };

export function AttachmentsPanel({
  projectId,
  scope,
  onClose,
}: {
  projectId: string;
  scope: AttachmentsScope;
  onClose: () => void;
}) {
  const sampleId = scope.kind === "sample" ? scope.sampleId : null;
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadErrors, setUploadErrors] = useState<string[]>([]);
  const [refreshingId, setRefreshingId] = useState<number | null>(null);
  const [mediaToken, setMediaToken] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setAttachments(
        sampleId
          ? await fetchSampleAttachments(projectId, sampleId)
          : await fetchAttachments(projectId),
      );
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "Could not load files",
      );
    } finally {
      setLoading(false);
    }
  }, [projectId, sampleId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    fetchSharePointHealth()
      .then((health) => setConfigured(health.configured))
      .catch(() => setConfigured(null));
  }, []);

  // Minted per scope and short-lived, so it is refetched rather than cached
  // across project or sample changes.
  useEffect(() => {
    let cancelled = false;
    fetchMediaToken(projectId)
      .then((token) => {
        if (!cancelled) setMediaToken(token);
      })
      .catch(() => {
        if (!cancelled) setMediaToken(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  // Escape closes, like the other modals in the app.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;

    setUploadErrors([]);

    // Accumulate instead of overwriting. Each file previously replaced the
    // previous error, so a batch of five with three failures reported only
    // the last one and the field crew re-uploaded files that had already
    // succeeded.
    const failures: string[] = [];
    let uploaded = 0;

    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        if (file.size > MAX_UPLOAD_BYTES) {
          failures.push(
            `${file.name} is ${formatSize(file.size)}; the limit is ${formatSize(
              MAX_UPLOAD_BYTES,
            )}.`,
          );
          continue;
        }

        try {
          const stored = sampleId
            ? await uploadSampleAttachment(projectId, sampleId, file)
            : await uploadAttachment(projectId, file);
          // Newest first, matching the server's ordering.
          setAttachments((current) => [stored, ...current]);
          uploaded += 1;
        } catch (caught) {
          failures.push(
            `${file.name}: ${
              caught instanceof Error ? caught.message : "Upload failed"
            }`,
          );
        }
      }
    } finally {
      // One flip rather than a flicker per file.
      setUploading(false);
      if (uploaded === 0 && failures.length === 0) {
        setUploadErrors(["No files were selected."]);
      } else if (failures.length > 0) {
        setUploadErrors(
          uploaded > 0
            ? [
                ...failures,
                `${uploaded} file${uploaded === 1 ? "" : "s"} uploaded successfully.`,
              ]
            : failures,
        );
      }
      // Allow the same file to be chosen again after a failure.
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  /** Graph preview URLs expire in about an hour; mint a fresh one. */
  async function handleRefreshPreview(attachment: Attachment) {
    setRefreshingId(attachment.id);
    setUploadErrors([]);
    try {
      const fresh =
        sampleId && scope.kind === "sample"
          ? await refreshSamplePreview(projectId, sampleId, attachment.id)
          : await refreshAttachmentPreview(attachment.project_id, attachment.id);
      setAttachments((current) =>
        current.map((item) =>
          item.id === attachment.id
            ? {
                ...item,
                preview_url: fresh.preview_url,
                preview_supported: fresh.preview_supported,
              }
            : item,
        ),
      );
    } catch (caught) {
      setUploadErrors([
        caught instanceof Error ? caught.message : "Refresh failed",
      ]);
    } finally {
      setRefreshingId(null);
    }
  }

  async function handleDelete(attachment: Attachment) {
    if (
      !window.confirm(
        `Remove "${attachment.filename}" from this project's list? The file stays in SharePoint.`,
      )
    ) {
      return;
    }

    try {
      await deleteAttachment(projectId, attachment.id);
      setAttachments((current) =>
        current.filter((item) => item.id !== attachment.id),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Remove failed");
    }
  }

  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div
        className="modal attachments-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Project attachments"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="attachments-head">
          <div>
            <div className="eyebrow">PROJECT FILES</div>
            <h2 className="attachments-title">
              {projectId}
              {sampleId ? ` / ${sampleId}` : ""}
            </h2>
          </div>
          <button type="button" className="btn" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="attachments-body">
          <div className="attachments-toolbar">
            <p className="attachments-hint">
              Images, video and documents are stored in SharePoint under{" "}
              <code>
                /{projectId}/{sampleId ? `samples/${sampleId}/` : ""}
              </code>
              .
            </p>

            {configured === null ? (
              <p className="attachments-status">
                Checking SharePoint availability…
              </p>
            ) : configured === false ? (
              <p className="warning-note">
                SharePoint is not configured on the server yet. Set
                AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID,
                SHAREPOINT_SITE_ID and SHAREPOINT_DRIVE_ID.
              </p>
            ) : (
              <div className="attachments-upload">
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  accept="image/*,video/*,.pdf,.doc,.docx,.xls,.xlsx,.dwg,.dxf"
                  onChange={(event) => handleFiles(event.target.files)}
                  disabled={uploading}
                />
                {uploading && <span className="attachments-status">Uploading…</span>}
              </div>
            )}
          </div>

          {!IS_HTTPS && attachments.some((a) => a.kind === "video") && (
            <p className="attachments-hint">
              This page is not served over HTTPS, so the browser will not
              allow seeking within a video. Serve the deployment over HTTPS.
            </p>
          )}

          {uploadErrors.length > 0 && (
            <div className="error-note">
              {uploadErrors.map((message) => (
                <div key={message}>{message}</div>
              ))}
            </div>
          )}
          {error && <p className="error-note">{error}</p>}

          {loading ? (
            <p className="attachments-status">Loading files…</p>
          ) : attachments.length === 0 ? (
            <p className="attachments-empty">
              No files yet. Upload site photos, videos or drawings.
            </p>
          ) : (
            <ul className="attachment-grid">
              {attachments.map((attachment) => (
                <li key={attachment.id} className="attachment-card">
                  <AttachmentView
                    attachment={attachment}
                    mediaToken={mediaToken}
                  />
                  <div className="attachment-meta">
                    <span className="attachment-name" title={attachment.filename}>
                      {attachment.filename}
                    </span>
                    <span className="attachment-sub">
                      {formatSize(attachment.size_bytes)} ·{" "}
                      {attachment.uploaded_by_username ?? "unknown"} ·{" "}
                      {formatDate(attachment.uploaded_at)}
                    </span>
                  </div>
                  <div className="attachment-actions">
                    <a
                      className="btn"
                      href={attachment.web_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      SharePoint
                    </a>
                    {attachment.kind === "preview" && (
                      <button
                        type="button"
                        className="btn"
                        onClick={() => handleRefreshPreview(attachment)}
                        disabled={refreshingId === attachment.id}
                      >
                        {refreshingId === attachment.id
                          ? "Refreshing…"
                          : "Refresh preview"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn"
                      onClick={() => handleDelete(attachment)}
                    >
                      Remove
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
