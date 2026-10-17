import { useEffect, useMemo, useState } from "react";
import {
  fetchSampleQrCodes,
  type QrSample,
  type QrScope,
} from "../../../../api/qrCodes";
import type { LocaRecord } from "../../../../api/projects";

/**
 * QR code picker and print sheet for the Sample Register.
 *
 * Two steps. "Choose" picks a scope and a borehole, then ticks the samples
 * that match. "Print" lays the ticked ones out as a sheet and hands over to
 * the browser's own print dialog, which is also how the user saves it as a
 * PDF -- so there is no server-side PDF dependency and the sheet can be
 * re-printed without another request, because the SVGs are already in the
 * DOM.
 *
 * "Select all" only ever selects what the current filter returned. Narrowing
 * to BH-1 and ticking Select all cannot quietly sweep in other boreholes,
 * because the list it ticks is the list the server just sent.
 */

interface QrCodeModalProps {
  projectId: string;
  locas: LocaRecord[];
  /** The register's current filter, so an already-narrowed view keeps it. */
  initialLocaId?: string;
  /** The register's open view, so "these samples" means the same thing in
      both places rather than the modal defaulting to All. */
  initialScope?: QrScope;
  onClose: () => void;
}

type Step = "choose" | "print";

const SCOPES: { value: QrScope; label: string }[] = [
  { value: "all", label: "All samples" },
  { value: "soil", label: "Soil only" },
  { value: "rock", label: "Rock only" },
];

function depthLabel(sample: QrSample): string {
  if (sample.depth_from === null) return "--";
  if (sample.depth_to === null) return `${sample.depth_from} m`;
  return `${sample.depth_from} - ${sample.depth_to} m`;
}

export function QrCodeModal({
  projectId,
  locas,
  initialLocaId,
  initialScope = "all",
  onClose,
}: QrCodeModalProps) {
  const [step, setStep] = useState<Step>("choose");

  const [scope, setScope] = useState<QrScope>(initialScope);
  const [locaId, setLocaId] = useState<string>(
    initialLocaId && initialLocaId !== "ALL" ? initialLocaId : "ALL"
  );

  const [samples, setSamples] = useState<QrSample[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Refetch on every scope/location change. The tickable list IS the server
  // response, so what the user can select and what would get a QR are the
  // same set by construction rather than by two agreeing code paths.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchSampleQrCodes(projectId, scope, locaId === "ALL" ? undefined : locaId)
      .then((response) => {
        if (cancelled) return;
        setSamples(response.samples);
        // Default to everything matching the filter. Opening the picker
        // almost always means "all of these"; unticking is the exception.
        setSelected(new Set(response.samples.map((s) => s.sample_id)));
      })
      .catch((err) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Could not generate QR codes."
        );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, scope, locaId]);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const selectedSamples = useMemo(
    () => samples.filter((s) => selected.has(s.sample_id)),
    [samples, selected]
  );

  const allSelected =
    samples.length > 0 && samples.every((s) => selected.has(s.sample_id));

  function toggleAll() {
    // Only the samples currently in the list -- which is the current
    // filter's result, never the whole project.
    setSelected(
      allSelected ? new Set() : new Set(samples.map((s) => s.sample_id))
    );
  }

  function toggleOne(sampleId: string) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(sampleId)) next.delete(sampleId);
      else next.add(sampleId);
      return next;
    });
  }

  function handlePrint() {
    setStep("print");
    // Let React mount the sheet before the print dialog reads the DOM.
    window.setTimeout(() => window.print(), 150);
  }

  if (step === "print") {
    return (
      <PrintSheet
        samples={selectedSamples}
        projectId={projectId}
        onBack={() => setStep("choose")}
        onClose={onClose}
      />
    );
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal modal-wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="qr-picker-title"
      >
        <div className="panel-head">
          <h2 className="panel-title" id="qr-picker-title">
            Generate sample QR codes
          </h2>
          <button
            type="button"
            className="btn"
            onClick={onClose}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <div className="panel-body qr-picker-body">
          <div className="qr-picker-row">
            <div className="qr-picker-field">
              <span className="qr-picker-label">Sample type</span>
              <div className="qr-picker-radio-group">
                {SCOPES.map((option) => (
                  <label className="qr-picker-radio" key={option.value}>
                    <input
                      type="radio"
                      name="qr-scope"
                      value={option.value}
                      checked={scope === option.value}
                      onChange={() => setScope(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </div>

            <div className="qr-picker-field">
              <label htmlFor="qr-loca">Location / borehole</label>
              <select
                id="qr-loca"
                value={locaId}
                onChange={(event) => setLocaId(event.target.value)}
              >
                <option value="ALL">All locations</option>
                {locas.map((loca) => (
                  <option key={loca.loca_id} value={loca.loca_id}>
                    {loca.loca_id}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/*
           * Error and "no samples" are mutually exclusive. A failed request
           * leaves `samples` empty, so the empty-state text used to render
           * underneath the error and claim no approved samples existed --
           * the opposite of the truth, and actively misleading when the
           * failure was an old backend that does not serve this route at
           * all.
           */}
          {loading ? (
            <p className="page-sub">Loading samples&hellip;</p>
          ) : error ? (
            <p className="page-sub field-error">
              {error}
              <br />
              <span style={{ fontWeight: 400 }}>
                If this says the QR service was not found, the backend is
                running older code than this page. Restart or redeploy it.
              </span>
            </p>
          ) : samples.length === 0 ? (
            <p className="page-sub">
              No approved samples match this filter. Approve a sample in Field
              Data first, or widen the filter.
            </p>
          ) : (
            <>
              <div className="qr-picker-row qr-picker-counts">
                <label className="qr-picker-radio">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    ref={(el) => {
                      if (el) {
                        el.indeterminate =
                          !allSelected && selected.size > 0;
                      }
                    }}
                    onChange={toggleAll}
                  />
                  <strong>Select all ({samples.length})</strong>
                </label>
                <span className="page-sub">
                  {selected.size} of {samples.length} selected
                </span>
              </div>

              <div className="qr-picker-sample-list">
                {samples.map((sample) => (
                  <label
                    key={`${sample.kind}-${sample.sample_id}`}
                    className="qr-picker-sample-item"
                  >
                    <input
                      type="checkbox"
                      checked={selected.has(sample.sample_id)}
                      onChange={() => toggleOne(sample.sample_id)}
                    />
                    <span className="qr-picker-sample-id">
                      {sample.sample_id}
                    </span>
                    <span className="cell-dim">{sample.loca_id}</span>
                    <span className="cell-dim">{depthLabel(sample)}</span>
                    <span
                      className={
                        sample.kind === "rock"
                          ? "chip chip-warn"
                          : "chip chip-info"
                      }
                    >
                      {sample.kind}
                    </span>
                  </label>
                ))}
              </div>
            </>
          )}

          <div className="actions qr-picker-actions">
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handlePrint}
              disabled={selected.size === 0}
            >
              Print {selected.size} QR code{selected.size === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ============================================================
   PRINT SHEET
   ============================================================ */

interface PrintSheetProps {
  samples: QrSample[];
  projectId: string;
  onBack: () => void;
  onClose: () => void;
}

function PrintSheet({
  samples,
  projectId,
  onBack,
  onClose,
}: PrintSheetProps) {
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal qr-print-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="qr-print-title"
      >
        <div className="panel-head qr-print-no-print">
          <h2 className="panel-title" id="qr-print-title">
            Print preview &mdash; {samples.length} sample
            {samples.length === 1 ? "" : "s"}
          </h2>
          <div className="actions">
            <button type="button" className="btn" onClick={onBack}>
              Back
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => window.print()}
            >
              Print
            </button>
            <button type="button" className="btn" onClick={onClose}>
              Close
            </button>
          </div>
        </div>

        {/* Everything inside .qr-print-sheet is what a print job captures. */}
        <div className="qr-print-sheet">
          <div className="qr-print-grid">
            {samples.map((sample) => (
              <div
                className="qr-print-card"
                key={`${sample.kind}-${sample.sample_id}`}
              >
                <img
                  src={sample.qr_svg_data_url}
                  alt={`QR code for sample ${sample.sample_id}`}
                />
                <div className="qr-print-project">{projectId}</div>
                <div className="qr-print-sample">{sample.sample_id}</div>
                <div className="qr-print-meta">
                  {sample.loca_id} &middot; {depthLabel(sample)}
                </div>
                <div className="qr-print-kind">{sample.kind}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}