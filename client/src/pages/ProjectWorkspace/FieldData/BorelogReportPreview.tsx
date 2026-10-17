import { useEffect, useMemo, useState } from "react";
import {
  downloadBorelogDocx,
  downloadBorelogPdf,
  fetchBorelogReport,
  type BorelogColumn,
  type BorelogReportData,
  type BorelogReportRow,
} from "../../../api/borelogReport";

interface BorelogReportPreviewProps {
  projectId: string;
  locaId: string;
}

/**
 * Field Data → Overview: the borehole report.
 *
 * The whole hole as one continuous, depth-proportional log. A stratum 8 m thick
 * is drawn eight times taller than one 1 m thick, and an SPT test sits at the
 * depth of the base of its 45 cm drive -- the same point the PDF plots it at.
 * One scroll region, no page break: the screen does not paginate, the PDF does.
 *
 * Geometry, not a record list. Ten columns whose widths come from the server's
 * own column list -- the same centimetre widths the PDF lays out at -- and every
 * block inside a column absolutely positioned at `depth / maxDepth` as a
 * percentage. That is the only arrangement in which the thing on screen reads
 * as the log the PDF prints; laid out as table rows it collapses into a list of
 * records with no sense of depth at all.
 *
 * Every displayed number arrives computed from the server, which derives both
 * this and the PDF from one list of rows. Nothing here recomputes a value.
 */

/** Vertical pixels per metre of depth. Sets how tall the log is drawn. */
const PX_PER_METRE = 30;

/** Floor, so a shallow borehole still reads as a log rather than a strip. */
const MIN_LOG_HEIGHT_PX = 460;

/** Floor on a drawn stratum, so a thin band is still visible. */
const MIN_BAND_PCT = 0.28;

/**
 * A test's result is plotted at its true depth, but two tests closer together
 * than this would print their numbers on top of each other. Nudged apart when
 * needed so every value stays readable. The nudge is a fixed share of the log's
 * height, so it cannot move a test to a visibly wrong depth.
 */
const MIN_MARKER_GAP_PCT = 1.4;

/* Bands above and below the log, for the labels that are centred on the log's
   own edges. The 0.00 tick is centred on depth 0 and the termination note on the
   base of the hole, so without these half of each would sit outside the log and
   be clipped by the scroll container. The PDF has the same margins for the same
   reason: its axis label at the top and its termination note below the last
   rule. Symmetric, so the log itself still starts exactly at depth 0. */
const LOG_TOP_BAND_PX = 14;
const TERMINATION_BAND_PX = 34;

/* The note is a wide, centred banner. Whether it clears the last SPT values
   depends on where the final test sits, not on the depth alone: a deep hole
   whose last test is far above the base is as cramped as a shallow one. The
   component measures the actual gap between the two and decides from that --
   see `noteOverlapsLastTest`. */

/** v6 rotates nine hatch patterns through the profile column; these are the
 *  CSS equivalents, kept in the same order so layer N looks as it does on paper. */
const HATCH_CLASS: Record<string, string> = {
  "/": "borelog-hatch-fwd",
  "\\": "borelog-hatch-back",
  x: "borelog-hatch-cross",
  "-": "borelog-hatch-horizontal",
  "+": "borelog-hatch-plus",
  ".": "borelog-hatch-dot",
  "*": "borelog-hatch-star",
  o: "borelog-hatch-circle",
  O: "borelog-hatch-circle-lg",
};

/** Column ids in the order the PDF prints them. Widths come from the server. */
const COLUMN_ORDER = [
  "depth",
  "profile",
  "description",
  "thickness",
  "spt_depth",
  "blows_15",
  "blows_30",
  "blows_45",
  "n_value",
  "spt_plot",
] as const;

const COLUMN_LABELS: Record<string, string> = {
  depth: "Depth (m)",
  profile: "Soil Profile",
  description: "Description",
  thickness: "Thickness",
  spt_depth: "SPT Depth",
  blows_15: "15 cm",
  blows_30: "30 cm",
  blows_45: "45 cm",
  n_value: "SPT N-Value",
  spt_plot: "SPT Plot",
};

const BLOW_FIELDS = ["blows_15", "blows_30", "blows_45"] as const;

export function BorelogReportPreview({
  projectId,
  locaId,
}: BorelogReportPreviewProps) {
  const [data, setData] = useState<BorelogReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState<"pdf" | "docx" | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    setLoading(true);
    setError(null);
    setGenerateError(null);

    fetchBorelogReport(projectId, locaId)
      .then((report) => {
        if (!cancelled) {
          setData(report);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load the borelog report.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId, locaId]);

  async function handleGeneratePdf() {
    setGenerating("pdf");
    setGenerateError(null);

    try {
      await downloadBorelogPdf(projectId, locaId);
    } catch (err) {
      setGenerateError(
        err instanceof Error ? err.message : "Unable to generate the PDF.",
      );
    } finally {
      setGenerating(null);
    }
  }

  async function handleGenerateDocx() {
    setGenerating("docx");
    setGenerateError(null);

    try {
      await downloadBorelogDocx(projectId, locaId);
    } catch (err) {
      setGenerateError(
        err instanceof Error
          ? err.message
          : "Unable to generate the Word document.",
      );
    } finally {
      setGenerating(null);
    }
  }

  const hasContent = (data?.layers.length ?? 0) > 0;

  return (
    <div className="borelog-report">
      <div className="module-toolbar">
        <div>
          <div className="eyebrow">CONTINUOUS REPORT</div>
          <h3 className="panel-subtitle">Borelog Report</h3>
        </div>

        <div className="actions">
          <button
            type="button"
            className="btn"
            onClick={handleGenerateDocx}
            disabled={generating !== null || loading || !hasContent}
          >
            {generating === "docx" ? "Generating DOCX…" : "Generate DOCX"}
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleGeneratePdf}
            disabled={generating !== null || loading || !hasContent}
          >
            {generating === "pdf" ? "Generating PDF…" : "Generate PDF"}
          </button>
        </div>
      </div>

      {generateError && (
        <p className="page-sub field-error">{generateError}</p>
      )}

      {loading ? (
        <p className="page-sub">Loading borelog report…</p>
      ) : error ? (
        <p className="page-sub field-error">{error}</p>
      ) : !hasContent ? (
        <div className="empty-state">
          <h3>No borelog report</h3>
          <p>
            No borehole, SPT or rock records have been saved for this location
            yet. Add field data first.
          </p>
        </div>
      ) : (
        <ReportBody data={data} />
      )}
    </div>
  );
}

function ReportBody({ data }: { data: BorelogReportData }) {
  const header = data.header;
  const summary = data.summary;
  const columns = data.columns?.length ? data.columns : fallbackColumns();

  const flexFor = (id: string) => {
    const column = columns.find((candidate) => candidate.id === id);
    return column?.percent ?? 100 / COLUMN_ORDER.length;
  };

  /*
   * The full depth the log is drawn to. The deepest logged stratum and the
   * declared termination depth can disagree -- a hole drilled to 30 m whose last
   * stratum stops at 28 m still runs to 30 -- and the log has to cover both, or
   * the last couple of metres fall off the end of the axis.
   */
  const maxDepth = useMemo(() => {
    const deepestLayer = data.layers.reduce(
      (deepest, layer) => Math.max(deepest, layer.depth_to ?? 0),
      0,
    );
    return Math.max(deepestLayer, header.termination_depth ?? 0, 1);
  }, [data.layers, header.termination_depth]);

  const depthPct = (depth: number) => (depth / maxDepth) * 100;
  const bandPct = (thickness: number) =>
    Math.max(depthPct(thickness), MIN_BAND_PCT);

  const logHeightPx = Math.max(maxDepth * PX_PER_METRE, MIN_LOG_HEIGHT_PX);

  const depthTicks = useMemo(() => {
    const step = maxDepth <= 20 ? 2 : maxDepth <= 50 ? 5 : 10;
    const ticks: number[] = [];
    for (let depth = 0; depth <= maxDepth; depth += step) {
      ticks.push(depth);
    }
    // Always label the base of the hole, even when it is not on the step.
    if (ticks[ticks.length - 1] !== maxDepth) {
      ticks.push(maxDepth);
    }
    return ticks;
  }, [maxDepth]);

  /*
   * Marker positions. Overlapping tests are nudged apart, because a number
   * printed on top of another is unreadable and both would be wrong to omit.
   * The nudge is applied here rather than in CSS because only the data knows how
   * close the tests are, and it is bounded so a test never leaves its depth.
   */
  const markerTop = useMemo(() => {
    const ordered = [...data.spt].sort(
      (a, b) => testDepth(a) - testDepth(b),
    );

    const tops = new Map<number, number>();
    let previous = -Infinity;

    for (const test of ordered) {
      const at = Math.min(
        Math.max(depthPct(testDepth(test)), previous + MIN_MARKER_GAP_PCT),
        100,
      );
      tops.set(test.spt_depth ?? 0, at);
      previous = at;
    }

    return (test: BorelogReportRow) =>
      tops.get(test.spt_depth ?? 0) ?? depthPct(testDepth(test));
  }, [data.spt, maxDepth]);

  /* The water table is ruled across the description column rather than the
   * whole log: that is where the PDF draws it, and a rule through the SPT
   * columns would cut across numbers the reader is following. Derived from the
   * same column percentages as everything else, so it tracks the layout. */
  const descriptionBand = useMemo(() => {
    const before = COLUMN_ORDER.slice(
      0,
      COLUMN_ORDER.indexOf("description"),
    ).reduce((total, id) => total + flexFor(id), 0);

    return {
      left: `${before}%`,
      width: `${flexFor("description")}%`,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columns]);

  /*
   * Whether the termination banner would cover the last SPT values.
   *
   * The banner is about 23 px tall and centred on the base of the hole, so it
   * reaches roughly 12 px above that base. The deepest marker reaches 7 px
   * below its own depth. So the banner clears the last test when there is more
   * than about 19 px of log between them -- about 0.6 m at 30 px per metre.
   * Measured rather than guessed, because it depends on where the last test
   * happens to be, not on the depth: a deep hole whose final test sits well
   * above the base is exactly as cramped as a shallow one.
   */
  const noteOverlapsLastTest = useMemo(() => {
    const lastTest = data.spt.reduce(
      (deepest, test) => Math.max(deepest, testDepth(test)),
      0,
    );
    const gapPx = (maxDepth - lastTest) * PX_PER_METRE;
    return gapPx < 19;
  }, [data.spt, maxDepth, logHeightPx]);

  const waterTable = header.water_table;
  const termination = header.termination_depth;

  return (
    <div className="borelog-report-sheet">
      {/* The header block, in the reading order the PDF prints it. */}
      <div className="borelog-report-title">
        {header.title.split("\n").map((line, index) => (
          <div key={index}>{line}</div>
        ))}
      </div>

      <dl className="borelog-report-meta">
        <MetaItem label="Client" value={header.client_name} />
        <MetaItem label="Borehole No" value={header.borehole_number} />
        <MetaItem label="Type of Boring" value={header.boring_type} />
        <MetaItem
          label="Termination Depth"
          value={termination !== null ? `${termination.toFixed(2)} m` : ""}
        />
        <MetaItem label="Boring Start Date" value={header.drilling_start} />
        <MetaItem
          label="Completion Date"
          value={header.drilling_completion}
        />
        <MetaItem label="Ground Water Table" value={header.water_table_text} />
        <MetaItem label="Location" value={header.project_location} />
      </dl>

      <p className="page-sub borelog-report-note">
        Continuous log for the full depth.{" "}
        <span className="borelog-report-counts">
          {countLabel(summary.layer_count, "layer")}
          {summary.spt_count > 0 ? ` · ${summary.spt_count} SPT` : ""}
          {summary.rock_count > 0
            ? ` · ${countLabel(summary.rock_count, "rock run")}`
            : ""}
        </span>
      </p>

      <div className="borelog-report-scroll">
        {/* Column headers sit outside the scrolling body so they stay put while
            the log scrolls under them. The leading cell matches the scale
            gutter below, so every header lines up with its column. */}
        <div className="borelog-columns">
          <div className="borelog-column-header borelog-column-header--scale">
            m
          </div>
          {COLUMN_ORDER.map((id) => (
            <div
              key={id}
              className="borelog-column-header"
              style={{ flex: flexFor(id) }}
            >
              {COLUMN_LABELS[id]}
            </div>
          ))}
        </div>

        {/* The scale gutter and the log. Both are pinned to the log's own height
            rather than stretched to the body: the body is taller by the
            termination band, and a stretched axis would put every tick at the
            wrong depth. */}
        <div
          className="borelog-body"
          style={{
            paddingTop: LOG_TOP_BAND_PX,
            height:
              logHeightPx +
              LOG_TOP_BAND_PX +
              (termination !== null ? TERMINATION_BAND_PX : 0),
          }}
        >
          <div className="borelog-scale" style={{ height: logHeightPx }}>
            {depthTicks.map((depth) => (
              <div
                key={`tick-${depth}`}
                className="borelog-depth-tick"
                style={{ top: `${depthPct(depth)}%` }}
              >
                {depth.toFixed(2)}
              </div>
            ))}
          </div>

          <div className="borelog-log" style={{ height: logHeightPx }}>
            <LogColumn width={flexFor("depth")}>
              {/* The depth of each stratum base, where the PDF prints it and
                  where the rule falls. */}
              {data.layers.map((layer, index) => (
                <div
                  key={`depth-${index}`}
                  className="borelog-stratum-depth"
                  style={{ top: `${depthPct(layer.depth_to ?? 0)}%` }}
                >
                  {layer.depth_to?.toFixed(2)}
                </div>
              ))}
            </LogColumn>

            {/* Soil profile: one continuous hatched strip, a stratum as tall as
                it is thick. */}
            <LogColumn width={flexFor("profile")}>
              {data.layers.map((layer, index) => (
                <div
                  key={`profile-${index}`}
                  className={`borelog-profile-bar ${
                    layer.is_rock
                      ? "borelog-profile-rock"
                      : (HATCH_CLASS[layer.hatch] ?? HATCH_CLASS["/"])
                  }`}
                  style={{
                    top: `${depthPct(layer.depth_from ?? 0)}%`,
                    height: `${bandPct(layer.thickness ?? 0)}%`,
                  }}
                  title={`${layer.depth_from?.toFixed(2)} – ${layer.depth_to?.toFixed(2)} m · ${
                    layer.description || "Unclassified material"
                  }`}
                />
              ))}
            </LogColumn>

            <LogColumn width={flexFor("description")}>
              {data.layers.map((layer, index) => (
                <div
                  key={`desc-${index}`}
                  className="borelog-description-cell"
                  style={{
                    top: `${depthPct(layer.depth_from ?? 0)}%`,
                    height: `${bandPct(layer.thickness ?? 0)}%`,
                  }}
                >
                  <div className="borelog-desc-text">
                    {layer.description || "Unclassified material"}
                  </div>
                  {layer.is_rock && (
                    <div className="borelog-rock-detail">
                      CORE RECOVERY = {layer.recovery_text}
                      <br />
                      RQD = {layer.rqd_text}
                      {layer.remark && (
                        <>
                          <br />
                          {layer.remark}
                        </>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </LogColumn>

            {/* Thickness, centred in its band as on the sheet. */}
            <LogColumn width={flexFor("thickness")}>
              {data.layers.map((layer, index) => (
                <div
                  key={`thickness-${index}`}
                  className="borelog-thickness-cell"
                  style={{
                    top: `${depthPct(layer.depth_from ?? 0)}%`,
                    height: `${bandPct(layer.thickness ?? 0)}%`,
                  }}
                >
                  {layer.thickness?.toFixed(2)}
                </div>
              ))}
            </LogColumn>

            <LogColumn width={flexFor("spt_depth")}>
              {data.spt.map((test, index) => (
                <Marker key={`spt-depth-${index}`} top={markerTop(test)}>
                  {test.spt_depth_text}
                </Marker>
              ))}
            </LogColumn>

            {BLOW_FIELDS.map((field) => (
              <LogColumn key={field} width={flexFor(field)}>
                {data.spt.map((test, index) => (
                  <Marker key={`${field}-${index}`} top={markerTop(test)}>
                    {test[field] ?? ""}
                  </Marker>
                ))}
              </LogColumn>
            ))}

            <LogColumn width={flexFor("n_value")}>
              {data.spt.map((test, index) => (
                <Marker key={`n-${index}`} top={markerTop(test)}>
                  {test.n_text}
                </Marker>
              ))}
            </LogColumn>

            {/* The plot strip: the dot at the same fraction across the column
                the PDF places it, so an N of 45 reads the same width on both. */}
            <LogColumn width={flexFor("spt_plot")}>
              {data.spt.map((test, index) => (
                <div
                  key={`plot-${index}`}
                  className="borelog-spt-plot-marker"
                  style={{ top: `${markerTop(test)}%` }}
                >
                  <div className="borelog-plot-track">
                    {test.n_plot_fraction !== null && (
                      <div
                        className="borelog-plot-dot"
                        style={{ left: `${test.n_plot_fraction * 100}%` }}
                      />
                    )}
                  </div>
                  {test.n_plot_text && (
                    <span className="borelog-plot-annot">
                      {test.n_plot_text}
                    </span>
                  )}
                </div>
              ))}
            </LogColumn>

            {/* The markers live inside the log, because the log is the depth
                axis: a percentage here resolves against the full depth. As
                siblings of the log they would resolve against the taller body
                and both would sit too low. */}
            {waterTable !== null && (
              <div
                className="borelog-water-table"
                style={{
                  top: `${depthPct(waterTable)}%`,
                  left: descriptionBand.left,
                  width: descriptionBand.width,
                }}
              >
                <span>Water Table at {waterTable.toFixed(2)} m</span>
              </div>
            )}

            {termination !== null && (
              <div
                className={`borelog-termination${
                  noteOverlapsLastTest ? " borelog-termination--in-band" : ""
                }`}
                style={{ top: `${depthPct(termination)}%` }}
              >
                <span>
                  THE BOREHOLE WAS TERMINATED AT {termination.toFixed(2)} m DEPTH
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** One track of the log: the positioning context for its blocks. */
function LogColumn({
  width,
  children,
}: {
  width: number;
  children: React.ReactNode;
}) {
  return (
    <div className="borelog-col" style={{ flex: width }}>
      {children}
    </div>
  );
}

/** One SPT value, placed at its test depth. */
function Marker({
  top,
  children,
}: {
  top: number;
  children: React.ReactNode;
}) {
  return (
    <div className="borelog-spt-marker" style={{ top: `${top}%` }}>
      {children}
    </div>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="borelog-report-meta-item">
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

/** Where a test's result is plotted: the base of the drive, or the start depth
 *  for a worded test. The server sends it; this is the fallback for a payload
 *  that predates the field. */
function testDepth(test: BorelogReportRow): number {
  return test.spt_test_depth ?? test.spt_depth ?? 0;
}

function countLabel(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function fallbackColumns(): BorelogColumn[] {
  return COLUMN_ORDER.map((id) => ({
    id,
    label: COLUMN_LABELS[id],
    label_lines: [COLUMN_LABELS[id]],
    percent: 100 / COLUMN_ORDER.length,
    rotated: false,
  }));
}