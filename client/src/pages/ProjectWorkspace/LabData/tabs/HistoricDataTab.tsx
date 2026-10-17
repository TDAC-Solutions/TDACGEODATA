import { useEffect, useState } from "react";
 import { getLabResults, type LabResultRow } from "../../../../api/lab";
 import { getLabMethods, type LabMethod } from "../../../../api/labMethods";

 /** Database status -> the words the laboratory uses. */
 const STATUS_LABEL: Record<string, string> = {
   APPROVED: "Approved (not released)",
   PUBLISHED: "Released to AGS",
 };

/**
 * The released values, rendered per test type in the order a lab sheet
 * reads them. Well-known keys come first and unknown keys still show (so a
 * new engine output never disappears), and non-numeric sentinels like NP
 * stay visible as text.
 */
const OUTPUT_ORDER: Record<string, string[]> = {
  ATTERBERG: ["liquid_limit", "plastic_limit", "plasticity_index", "flow_index"],
  PARTICLE_DENSITY: ["specific_gravity", "particle_density"],
  PSD: [
    "gravel_pct", "sand_pct", "fines_pct", "silt_pct", "clay_pct",
    "d10_mm", "d30_mm", "d60_mm", "cu", "cc",
  ],
};

function releasedOutputsCell(
  testType: string,
  outputs: Record<string, number>
): string {
  const entries = Object.entries(outputs ?? {});
  if (entries.length === 0) return "—";

  const order = OUTPUT_ORDER[testType] ?? [];
  const ordered: [string, number][] = [];
  const seen = new Set<string>();

  for (const key of order) {
    if (key in outputs) {
      ordered.push([key, outputs[key]]);
      seen.add(key);
    }
  }
  for (const [key, value] of entries) {
    if (!seen.has(key)) ordered.push([key, value]);
  }

  return ordered.map(([key, value]) => `${key}=${value}`).join(", ");
}

 function formatNumber(value: number | null): string {
   if (value === null || value === undefined) return "—";
   return String(value);
 }

 function statusLabel(status: string) {
   return STATUS_LABEL[status] ?? status;
 }

 interface HistoricFilter {
   sample: string;
   depthRange: string;
   test: string;
 }

 const EMPTY_FILTER: HistoricFilter = {
   sample: "",
   depthRange: "",
   test: "",
 };

 interface HistoricDataTabProps {
   projectId: string;
 }

 export function HistoricDataTab({ projectId }: HistoricDataTabProps) {
   const [filter, setFilter] = useState({
     ...EMPTY_FILTER,
     project: projectId,
   });

   const [results, setResults] = useState<LabResultRow[]>([]);
   const [methods, setMethods] = useState<LabMethod[]>([]);
   const [loading, setLoading] = useState(true);
   const [error, setError] = useState<string | null>(null);

   // The test-type filter lists the test types the laboratory's active method
   // definitions actually cover, so the options come from the database.
   useEffect(() => {
     getLabMethods()
       .then(setMethods)
       .catch(() => setMethods([]));
   }, []);

   const testTypeOptions = Array.from(
     new Set(methods.map((method) => method.test_type))
   ).sort();

   // Exports exactly the rows on screen. This is the same query result the
   // table renders - no second data source.
   function exportSelection() {
     const header = [
       "TEST_ID",
       "PROJ_ID",
       "LOCA_ID",
       "SAMP_ID",
       "SPEC_REF",
       "DEPTH",
       "TEST_TYPE",
       "STATUS",
       "LL",
       "PI",
     ];

     // RFC 4180 escaping. A specimen reference or laboratory name holding a
     // comma, quote or newline would otherwise shift every column after it,
     // and Excel splits on those silently. Quote whenever the value contains
     // a delimiter, a quote or a line break, and double any embedded quote.
     const escapeCsv = (value: unknown): string => {
       if (value === null || value === undefined) return "";

       const text = String(value);

       if (/[",\r\n]/.test(text)) {
         return `"${text.replace(/"/g, '""')}"`;
       }

       return text;
     };

     const csv = [
       header.map(escapeCsv).join(","),
       ...results.map((row) =>
         [
           row.test_id,
           row.proj_id,
           row.loca_id,
           row.sample_id,
           row.spec_ref ?? "",
           row.depth ?? "",
           row.test_type,
           row.status,
           row.ll ?? "",
           row.pi ?? "",
         ]
           .map(escapeCsv)
           .join(",")
       ),
     ].join("\n");

     const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
     const link = document.createElement("a");
     link.href = url;
     link.download = `historic-lab-results-${projectId}.csv`;
     link.click();
     URL.revokeObjectURL(url);
   }

   function setField(field: keyof HistoricFilter, value: string) {
       setFilter((current) => ({ ...current, [field]: value }));
     }

     // Parses the free-text depth range ("5-15", "5", or "5 to 15") into
     // [depth_from, depth_to]. Unparseable input yields both undefined so the
     // query simply omits the depth filter instead of erroring.
     function parseDepthRange(raw: string): { from?: number; to?: number } {
       const trimmed = raw.trim();

       if (trimmed === "") {
         return {};
       }

       // Accepts "5-15", "5 15", "5 to 15" and any mix. The separator must
       // be explicit: matching bare whitespace first would swallow the space
       // in "5 to 15" and leave "to" attached to a number, which Number()
       // turns into 0 rather than NaN.
       const parts = trimmed
         .split(/\s*(?:-|to\b)\s*|\s+/i)
         .map((part) => Number(part))
         .filter((value) => Number.isFinite(value) && !Number.isNaN(value));

       if (parts.length === 1) {
         return { from: parts[0] };
       }

       if (parts.length >= 2) {
         const from = Math.min(parts[0], parts[1]);
         const to = Math.max(parts[0], parts[1]);
         return { from, to };
       }

       return {};
     }

     useEffect(() => {
       let cancelled = false;

       async function load() {
         try {
           setLoading(true);
           setError(null);

           const depth = parseDepthRange(filter.depthRange);

           const data = await getLabResults(projectId, {
             sample: filter.sample,
             depth_from: depth.from,
             depth_to: depth.to,
             test_type: filter.test,
           });

           if (!cancelled) {
             setResults(data);
           }
         } catch (err) {
           if (!cancelled) {
             setError(
               err instanceof Error ? err.message : "Failed to load results"
             );
           }
         } finally {
           if (!cancelled) {
             setLoading(false);
           }
         }
       }

       // Debounced. Typing "BH-03" in the sample box used to fire five
       // requests (B, BH, BH-, BH-0, BH-03), each hitting the database
       // and rendering. A short wait collapses that into one.
       const handle = window.setTimeout(load, 350);

       return () => {
         cancelled = true;
         window.clearTimeout(handle);
       };
     }, [projectId, filter.sample, filter.depthRange, filter.test]);

   return (
     <div>
       <div className="module-toolbar">
         <div>
           <div className="eyebrow">EXISTING AND COMPLETED PROJECTS</div>
           <h3 className="panel-subtitle">Historic Laboratory Results</h3>
         </div>

         <div className="actions">
           <button
             type="button"
             className="btn btn-sm btn-primary"
             onClick={exportSelection}
             disabled={results.length === 0}
           >
             Export selection ({results.length})
           </button>
         </div>
       </div>

       <div className="card">
         <h3>Filter</h3>

         <div className="form-grid">
           <label>
             <span className="eyebrow">Project</span>
             {/* The module is opened from a project workspace, so the query is
                 always scoped to that project - shown, not chosen. */}
             <input className="modal-input" value={projectId} readOnly />
           </label>

           <label>
             <span className="eyebrow">Location / sample</span>
             <input
               className="modal-input"
               placeholder="BH, sample or specimen ID"
               value={filter.sample}
               onChange={(event) => setField("sample", event.target.value)}
             />
           </label>

           <label>
             <span className="eyebrow">Depth range (m)</span>
             <input
               className="modal-input"
               placeholder="e.g. 5-15"
               value={filter.depthRange}
               onChange={(event) => setField("depthRange", event.target.value)}
             />
           </label>

           <label>
             <span className="eyebrow">Test / parameter</span>
             <select
               className="modal-input"
               value={filter.test}
               onChange={(event) => setField("test", event.target.value)}
             >
               <option value="">All laboratory tests</option>

               {testTypeOptions.map((testType) => (
                 <option key={testType} value={testType}>
                   {testType}
                 </option>
               ))}
             </select>
           </label>
         </div>
       </div>

       <div className="card" style={{ marginTop: "12px" }}>
         <h3>Released result matrix</h3>

         {loading ? (
           <div className="empty-state">
             <h3>Loading results...</h3>
           </div>
         ) : error ? (
           <div className="empty-state">
             <h3>Could not load results</h3>
             <p>{error}</p>
           </div>
         ) : results.length === 0 ? (
           <div className="empty-state">
             <h3>No released results for this filter</h3>
             <p>
               Approved and published laboratory results appear here. Approve a
               revision on the QA and Approval tab, then Publish it to release
               the values.
             </p>
           </div>
         ) : (
           <div className="table-scroll table-scroll--no-cards">
             <table className="dtable">
               <thead>
                 <tr>
                   <th>Project</th>
                   <th>Location</th>
                   <th>Sample / specimen</th>
                   <th>Depth (m)</th>
                   <th>Test</th>
                   <th>LL</th>
                   <th>PI</th>
                   <th>Released values</th>
                   <th>Status</th>
                 </tr>
               </thead>
               <tbody>
                 {results.map((result) => (
                   <tr key={result.test_id}>
                     <td>{result.proj_id}</td>
                     <td>{result.loca_id}</td>
                     <td>
                       {result.sample_id}
                       {result.spec_ref ? ` · ${result.spec_ref}` : ""}
                     </td>
                     <td className="num">{result.depth ?? "—"}</td>
                     <td>{result.test_type}</td>
                     <td className="num">{formatNumber(result.ll)}</td>
                     <td className="num">{formatNumber(result.pi)}</td>
                     <td className="cell-dim">
                       {/* The released output keys carried by the current
                           revision snapshot, read straight from the database,
                           ordered like a lab sheet per test type. */}
                       {releasedOutputsCell(result.test_type, result.outputs)}
                     </td>
                     <td>
                       <span
                         className={
                           result.status === "PUBLISHED"
                             ? "chip chip-ok"
                             : "chip chip-info"
                         }
                       >
                         {statusLabel(result.status)}
                       </span>
                     </td>
                   </tr>
                 ))}
               </tbody>
             </table>
           </div>
         )}
       </div>

       <div className="card" style={{ marginTop: "12px" }}>
         <h3>Data provenance</h3>

         <div className="table-scroll table-scroll--no-cards">
           <table className="dtable">
             <tbody>
               <tr>
                 <td>Rows shown</td>
                 <td>
                   {results.length} released test(s):{" "}
                   {results.filter((row) => row.status === "APPROVED").length}{" "}
                   approved,{" "}
                   {results.filter((row) => row.status === "PUBLISHED").length}{" "}
                   published
                 </td>
               </tr>
               <tr>
                 <td>Source of values</td>
                 <td>
                   lab.test_revision.calculation_output_snapshot for the current
                   revision of each test
                 </td>
               </tr>
               <tr>
                 <td>Unit handling</td>
                 <td>Values are shown as stored on the revision; no conversion</td>
               </tr>
               <tr>
                 <td>Excluded by the query</td>
                 <td>
                   Draft, calculated, submitted, checked, returned, superseded
                   and void tests
                 </td>
               </tr>
             </tbody>
           </table>
         </div>

         <p className="paper-note">
           The summary is a query over released results. It is not a manually
           maintained duplicate table.
         </p>
       </div>
     </div>
   );
 }
