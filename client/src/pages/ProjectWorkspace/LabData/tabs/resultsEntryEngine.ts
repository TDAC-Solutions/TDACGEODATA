/* Pure calculation + validation for Results Entry. No UI, no I/O.

   PREVIEW ONLY for PSD, PARTICLE_DENSITY and ATTERBERG: the server engine
   (server/app/lab_engine, ported from the TDAC Basic Lab Developer Package)
   is the calculation authority and recomputes the stored snapshot on every
   save. This local engine still drives the instant in-form preview (and
   remains the only calculation for SHRINKAGE_LIMIT, TRIAXIAL_UU and
   CONSOLIDATION, which the package does not cover). It mirrors the server's
   validation rules where the form captures the needed inputs, so preview
   and server agree; when they differ, the server wins. */

export type TestKey =
  | "PSD"
  | "PARTICLE_DENSITY"
  | "ATTERBERG"
  | "SHRINKAGE_LIMIT"
  | "TRIAXIAL_UU"
  | "CONSOLIDATION";

export type Row = Record<string, string>;

export interface MethodData {
  params: Record<string, string>;
  rows: Row[];
  rows2?: Row[];
}

export interface Issue {
  level: "error" | "warning" | "info";
  message: string;
}

export interface ResultItem {
  label: string;
  value: string;
  unit?: string;
}

export interface Evaluation {
  results: ResultItem[];
  issues: Issue[];
  /** Calculated series for plotting */
  curve?: { x: number; y: number }[];
  /** Calculated cells per input row (same index as data.rows) */
  perRow?: Row[];
  /** Extra AGS preview lines (only where the heading is certain) */
  ags?: string[];
}

const num = (s: string | undefined) =>
  s === undefined || s.trim() === "" ? NaN : Number(s);
const fmt = (n: number, d = 2) => (Number.isFinite(n) ? n.toFixed(d) : "—");

/**
 * Form-shape defaults per test: method profile name and the ROW SHAPE
 * (which cells a row carries) - but NO example values. Every grid starts
 * empty; all data is entered by the user against a real test.
 */
export function defaultMethodData(test: TestKey): MethodData {
  switch (test) {
    case "PSD":
      return {
        params: {
          // No seeded method text: the profile is chosen from the active
          // method definitions read from lab.method_definition.
          method: "",
          dryMass: "",
          particleDensity: "",
          panMass: "",
          washLoss: "",
          massTolerance: "",
          pretreatment: "",
        },
        rows: [],
      };
    case "PARTICLE_DENSITY":
      return {
        params: {
          method: "",
          pycnometer: "",
          fraction: "",
        },
        rows: [],
      };
    case "SHRINKAGE_LIMIT":
      return {
        params: {
          method: "",
          initialWc: "",
          initialDensity: "",
          preparation: "",
        },
        rows: [],
      };
    case "TRIAXIAL_UU":
      return {
        params: {
          method: "",
          condition: "",
          frame: "",
          failureCriterion: "Peak deviator stress",
        },
        rows: [],
      };
    default:
      return { params: {}, rows: [] };
  }
}

/** Water density (kg/m³), Kell (1975), 0–40 °C. */
function rhoW(t: number) {
  return (
    (999.83952 + 16.945176 * t - 7.9870401e-3 * t ** 2 - 46.170461e-6 * t ** 3 +
      105.56302e-9 * t ** 4 - 280.54253e-12 * t ** 5) /
    (1 + 16.87985e-3 * t)
  );
}

function waterContent(r: Row) {
  const c = num(r.containerMass), w = num(r.wetContainer), d = num(r.dryContainer);
  return ((w - d) / (d - c)) * 100;
}

/** D at percent-passing p, log-linear between bracketing sieves. */
function dAt(pts: { x: number; y: number }[], p: number): number {
  const s = [...pts].sort((a, b) => a.x - b.x);
  for (let i = 0; i < s.length - 1; i++) {
    const a = s[i], b = s[i + 1];
    if (a.y <= p && p <= b.y && b.y !== a.y) {
      const t = (p - a.y) / (b.y - a.y);
      return Math.pow(10, Math.log10(a.x) + t * (Math.log10(b.x) - Math.log10(a.x)));
    }
  }
  return NaN;
}

export function evaluate(test: TestKey, d: MethodData): Evaluation {
  const issues: Issue[] = [];
  const results: ResultItem[] = [];
  const err = (m: string) => issues.push({ level: "error", message: m });
  const warn = (m: string) => issues.push({ level: "warning", message: m });
  const info = (m: string) => issues.push({ level: "info", message: m });
  let curve: Evaluation["curve"];

  const perRow: Row[] = d.rows.map(() => ({}));
  let agsLines: string[] | undefined;

  if (test === "PSD") {
    const total = num(d.params.dryMass);
    if (!(total > 0)) err("Dry specimen mass is required and must be > 0.");
    // Blank tare = 0, matching the server engine (`_num(row.get("tare")) or 0.0`).
    // Treating a blank tare as a missing reading rejected rows the server
    // accepts, so the preview and the stored calculation disagreed.
    const tareOf = (r: Row) => {
      const tare = num(r.tare);
      return Number.isFinite(tare) ? tare : 0;
    };
    const items = d.rows.map((r, i) => ({ i, size: num(r.size), ret: num(r.tareRet) - tareOf(r) }));
    const filled = items.filter((x) => d.rows[x.i].size.trim() !== "" || d.rows[x.i].tareRet.trim() !== "");
    const seen = new Set<number>();
    const good: typeof items = [];
    filled.forEach((x) => {
      const r = d.rows[x.i], n = x.i + 1;
      if (!(x.size > 0)) return err(`Row ${n}: sieve size must be a number > 0.`);
      if (seen.has(x.size)) err(`Row ${n}: duplicate sieve size ${x.size}.`);
      seen.add(x.size);
      if (Number.isNaN(x.ret)) return warn(`Sieve ${x.size} mm: tare + retained is required (tare defaults to 0).`);
      if (x.ret < 0) return err(`Sieve ${x.size} mm: tare + retained is less than tare.`);
      if (!r.gratType.trim()) warn(`Sieve ${x.size} mm: GRAT_TYPE not set.`);
      good.push(x);
    });
    if (!good.length) err("No sieve readings entered.");
    let cum = 0;
    const pts: { x: number; y: number }[] = [];
    [...good].sort((a, b) => b.size - a.size).forEach((x) => {
      cum += x.ret;
      const pass = total > 0 ? (1 - cum / total) * 100 : NaN;
      perRow[x.i] = { retained: fmt(x.ret), cumulative: fmt(cum), passing: fmt(pass, 1) };
      if (Number.isFinite(pass)) pts.push({ x: x.size, y: pass });
    });
    // Mass reconciliation against dry mass, matching the server engine's
    // rule: retained + pan + wash loss must close on the declared dry mass
    // within the lab's tolerance (default 0.5% when the field is blank).
    const pan = num(d.params.panMass) || 0;
    const wash = num(d.params.washLoss) || 0;
    const tolPct = num(d.params.massTolerance);
    const tol = Number.isFinite(tolPct) && tolPct >= 0 ? tolPct : 0.5;
    if (total > 0 && Number.isFinite(pan + wash)) {
      const recovered = cum + pan + wash;
      const diff = recovered - total;
      if (Math.abs(diff) > (total * tol) / 100)
        err(
          `Dry mass does not reconcile: recovered ${recovered.toFixed(3)} g differs by ${diff >= 0 ? "+" : ""}${diff.toFixed(3)} g, exceeding the ${tol}% tolerance.`
        );
      else
        results.push({
          label: "Mass balance",
          value: `${diff >= 0 ? "+" : ""}${fmt(diff, 3)} g of ${fmt(total, 3)} g dry mass (${fmt(tol, 2)}% tolerance)`,
        });
    }
    if (total > 0 && cum > total) err("Sum of retained masses exceeds dry specimen mass.");
    curve = pts;
    const at = (mm: number) => pts.find((p) => p.x === mm)?.y;
    // Gravel/sand boundary is the 4.75 mm sieve (IS 2720 Part 4, and the
    // mockup's own first sieve row), not the 2 mm fine-earth fraction.
    const pf = at(0.075) ?? at(0.063), p2 = at(4.75);
    if (p2 !== undefined && pf !== undefined) {
      results.push(
        { label: "Gravel", value: fmt(100 - p2, 1), unit: "%" },
        { label: "Sand", value: fmt(p2 - pf, 1), unit: "%" },
        { label: "Fines", value: fmt(pf, 1), unit: "%" }
      );
    } else if (pts.length) info("Gravel/sand/fines need the 4.75 mm and 0.075 (or 0.063) mm sieves.");
    results.push({ label: "Silt", value: "—" }, { label: "Clay", value: "—" });
    const d10 = dAt(pts, 10), d30 = dAt(pts, 30), d60 = dAt(pts, 60);
    if (Number.isFinite(d10) && Number.isFinite(d60)) {
      const cu = d60 / d10, cc = Number.isFinite(d30) ? (d30 * d30) / (d10 * d60) : NaN;
      // 2dp matches the server engine's display of Cu/Cc.
      results.push({ label: "Cu / Cc", value: `${fmt(cu, 2)} / ${fmt(cc, 2)}` });
    } else {
      results.push({ label: "Cu / Cc", value: "—" });
      if (pts.length) info("Cu/Cc not computable: D10/D60 outside the sieve range.");
    }
    if (!(num(d.params.particleDensity) > 0)) warn("Particle density not entered (needed for the hydrometer).");
    info("Hydrometer readings, silt/clay split and advanced GRAT/GRAG fields: pending.");
  }

  if (test === "PARTICLE_DENSITY") {
    const gs: number[] = [], pd: number[] = [];
    d.rows.forEach((r, i) => {
      const [m1, m2, m3, m4, t] = [r.m1, r.m2, r.m3, r.m4, r.temp].map(num);
      if ([m1, m2, m3, m4, t].every(Number.isNaN)) return;
      if ([m1, m2, m3, m4, t].some(Number.isNaN))
        return err(`Trial ${r.trial}: four masses and temperature are required.`);
      if (!(m2 > m1 && m4 > m1)) return err(`Trial ${r.trial}: masses must satisfy m2 > m1 and m4 > m1.`);
      if (t < 0 || t > 40) return err(`Trial ${r.trial}: temperature outside 0–40 °C.`);
      const den = (m4 - m1) - (m3 - m2);
      if (!(den > 0)) return err(`Trial ${r.trial}: invalid mass combination (denominator ≤ 0).`);
      const g = (m2 - m1) / den, p = (g * rhoW(t)) / 1000;
      perRow[i] = { gs: fmt(g, 3), pd: `${fmt(p, 3)} Mg/m3` };
      if (r.use !== "false") { gs.push(g); pd.push(p); }
    });
    if (!gs.length) err("No accepted, complete pycnometer trial.");
    else {
      const mg = gs.reduce((a, b) => a + b, 0) / gs.length, mp = pd.reduce((a, b) => a + b, 0) / pd.length;
      results.push({ label: "Mean Gs", value: fmt(mg, 3) }, { label: "Particle density", value: fmt(mp, 2), unit: "Mg/m3" });
      const vol = /(\d+(?:\.\d+)?)\s*ml/i.exec(d.params.pycnometer ?? "");
      agsLines = [`LPDN_PDEN = ${fmt(mp, 2)}`, "LPDN_TYPE = PYCNOMETER", ...(vol ? [`LPDN_PVOL = ${vol[1]}`] : [])];
    }
    info("Trial-spread acceptance limit and calibration link: pending (method package rules).");
  }

  if (test === "ATTERBERG") {
    const pts: { x: number; y: number }[] = [];
    d.rows.forEach((r, i) => {
      if (r.use === "false") return;
      const w = waterContent(r), n = num(r.blows);
      if (!Number.isFinite(w) || !(n > 0))
        return err(`Liquid trial ${i + 1}: blows and all three masses are required.`);
      if (!(num(r.dryContainer) > num(r.containerMass)) || !(num(r.wetContainer) >= num(r.dryContainer)))
        return err(`Liquid trial ${i + 1}: need wet ≥ dry > container mass.`);
      pts.push({ x: Math.log10(n), y: w });
    });
    const pl: number[] = [];
    (d.rows2 ?? []).forEach((r, i) => {
      const w = waterContent(r);
      if (!Number.isFinite(w)) return err(`Plastic trial ${i + 1}: three masses required.`);
      if (!(num(r.dryContainer) > num(r.containerMass)) || !(num(r.wetContainer) >= num(r.dryContainer)))
        return err(`Plastic trial ${i + 1}: need wet ≥ dry > container mass.`);
      pl.push(w);
    });
    let LL = NaN, FI = NaN;
    if (pts.length < 3) err("At least 3 liquid-limit trials are required for the flow curve.");
    else {
      const n = pts.length, sx = pts.reduce((a, p) => a + p.x, 0), sy = pts.reduce((a, p) => a + p.y, 0);
      const sxx = pts.reduce((a, p) => a + p.x * p.x, 0), sxy = pts.reduce((a, p) => a + p.x * p.y, 0);
      const den = n * sxx - sx * sx;
      if (den === 0) err("Blow counts must differ to fit a flow curve.");
      else {
        const m = (n * sxy - sx * sy) / den, c = (sy - m * sx) / n;
        LL = c + m * Math.log10(25);
        FI = -m;
        if (FI < 0) warn("Flow curve slope is positive (water content rises with blows).");
        if (!pts.some((p) => Math.abs(Math.pow(10, p.x) - 25) <= 10))
          warn("No liquid-limit trial within 15–35 blows.");
      }
    }
    if (pl.length < 2) err("At least 2 plastic-limit trials are required.");
    const PL = pl.length ? pl.reduce((a, b) => a + b, 0) / pl.length : NaN;
    const PI = LL - PL;
    // Flow curve: real trial points plus the fitted least-squares line.
    // The regression runs on x = log10(blows); the curve stores x back in
    // blows (10^x) because the chart's x-axis is logarithmic, so the stored
    // x values are the blows counts the user entered.
    if (pts.length >= 2) {
      const xs = pts.map((p) => p.x);
      const x0 = Math.min(...xs), x1 = Math.max(...xs);
      const syy = pts.reduce((a, p) => a + p.y, 0);
      const sxy = pts.reduce((a, p) => a + p.x * p.y, 0);
      const xx = pts.reduce((a, p) => a + p.x * p.x, 0);
      const den = pts.length * xx - xs.reduce((a, p) => a + p, 0) ** 2;
      if (den !== 0) {
        const slope = (pts.length * sxy - xs.reduce((a, p) => a + p, 0) * syy) / den;
        const intercept = (syy - slope * xs.reduce((a, p) => a + p, 0)) / pts.length;
        const fitY = (x: number) => slope * x + intercept;
        curve = [
          ...pts.map((p) => ({ x: Math.pow(10, p.x), y: p.y })),
          { x: Math.pow(10, x0), y: fitY(x0) },
          { x: Math.pow(10, x1), y: fitY(x1) },
        ];
      }
    }
    // Decimals match the server engine's display (1dp limits, 2dp flow
    // index) so the divergence chip only fires on real disagreements,
    // never on display rounding.
    results.push(
      { label: "Liquid limit", value: fmt(LL, 1), unit: "%" },
      { label: "Plastic limit", value: fmt(PL, 1), unit: "%" },
      { label: "Plasticity index", value: fmt(PI, 1) },
      { label: "Flow index", value: fmt(FI, 2) }
    );
    if (Number.isFinite(PI) && PI < 0) err("Plasticity index is negative (PL > LL).");
    if (Number.isFinite(LL) && Number.isFinite(PI)) {
      const above = PI >= 0.73 * (LL - 20);
      results.push({
        label: "Classification aid (interpretation only)",
        value: (LL >= 50 ? "H" : "L") + (above ? " (above A-line)" : " (below A-line)"),
      });
    }
  }

  if (test === "SHRINKAGE_LIMIT") {
    const sl: number[] = [], sr: number[] = [];
    d.rows.forEach((r, i) => {
      const [mw, md, vw, vd] = [r.wetMass, r.dryMass, r.wetVol, r.dryVol].map(num);
      if ([mw, md, vw, vd].every(Number.isNaN)) return;
      if ([mw, md, vw, vd].some(Number.isNaN)) return err(`Trial ${r.trial}: wet/dry mass and wet/dry volume are required.`);
      if (![mw, md, vw, vd].every((v) => v > 0)) return err(`Trial ${r.trial}: masses and volumes must be > 0.`);
      if (md > mw) return err(`Trial ${r.trial}: dry mass exceeds wet mass.`);
      if (vd > vw) warn(`Trial ${r.trial}: dry volume exceeds wet volume.`);
      const w = ((mw - md) / md) * 100;
      const s1 = w - ((vw - vd) / md) * 100; // water density 1 g/cm³
      if (s1 < 0) return err(`Trial ${r.trial}: computed shrinkage limit is negative.`);
      perRow[i] = { sl: fmt(s1, 1), sr: fmt(md / vd, 2) };
      sl.push(s1); sr.push(md / vd);
    });
    if (!sl.length) err("No complete shrinkage trial entered.");
    else {
      const m = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
      results.push({ label: "Mean shrinkage limit", value: fmt(m(sl), 1), unit: "%" }, { label: "Mean shrinkage ratio", value: fmt(m(sr), 2) });
    }
    if (!(num(d.params.initialWc) >= 0)) warn("Initial water content not entered.");
    info("Formula assumes water density 1 g/cm³; method-package units, rounding and tolerances: pending.");
  }

  if (test === "TRIAXIAL_UU") {
    const cus: number[] = [], pts: { x: number; y: number }[] = [];
    d.rows.forEach((r, i) => {
      const v = [r.dia, r.length, r.cell, r.q, r.strain].map(num);
      if (v.every(Number.isNaN)) return;
      if (v.some(Number.isNaN)) return err(`Specimen ${r.spec}: dimensions, cell pressure, q and strain are required.`);
      const [dia, len, cell, q, strain] = v;
      if (!(dia > 0 && len > 0)) return err(`Specimen ${r.spec}: dimensions must be > 0.`);
      if (cell < 0 || strain < 0 || q < 0) return err(`Specimen ${r.spec}: negative value.`);
      if (!r.mode.trim()) warn(`Specimen ${r.spec}: failure mode not stated.`);
      perRow[i] = { cu: fmt(q / 2, 0) };
      cus.push(q / 2); pts.push({ x: strain, y: q });
    });
    if (!cus.length) err("No complete specimen entered.");
    else {
      results.push(
        { label: "Mean cu", value: fmt(cus.reduce((a, b) => a + b, 0) / cus.length, 1), unit: "kPa" },
        { label: "Range", value: `${fmt(Math.min(...cus), 0)}-${fmt(Math.max(...cus), 0)}`, unit: "kPa" },
        { label: "Specimens", value: `${cus.length} accepted` },
        { label: "Calculation", value: "qf / 2" }
      );
    }
    curve = pts;
    info("cu = qf/2 applies only to the UU method rule. Full stress–strain series entry: pending.");
  }

  if (test === "CONSOLIDATION") {
    err("Consolidation readings are display-only in this build (not bound to state): cannot calculate, save or submit.");
  }

  return { results, issues, curve, perRow, ags: agsLines };
}
