import { useEffect, useState } from "react";
import { createLoca, type LocaRecord } from "../../api/projects";

interface AddLocaModalProps {
  projectId: string | undefined;
  onClose: () => void;
  onCreated: (loca: LocaRecord) => void;
}

// Fixed vocabulary so every location records a type that can be filtered and
// counted. "Other" deliberately stores the literal string Other: if a site
// needs a free-text type, that is a separate field and a separate decision,
// not a silent escape hatch inside this list.
const LOCA_TYPE_OPTIONS = [
  { value: "BH", label: "BH - Borehole" },
  { value: "SPT", label: "SPT - Standard Penetration Test" },
  { value: "CPT", label: "CPT - Cone Penetration Test" },
  { value: "Sampling", label: "Sampling" },
  { value: "Other", label: "Other" },
];

export function AddLocaModal({
  projectId,
  onClose,
  onCreated,
}: AddLocaModalProps) {
  const [locaId, setLocaId] = useState("");
  const [locaType, setLocaType] = useState("BH");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [finalDepth, setFinalDepth] = useState("");

  const [groundLevel, setGroundLevel] = useState("");
  const [groundwaterDepth, setGroundwaterDepth] = useState("");
  const [easting, setEasting] = useState("");
  const [northing, setNorthing] = useState("");
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");

  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Escape closes, like the other modals in the app. Guarded on !saving so
  // a stray keypress cannot abandon a create that is already in flight.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !saving) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saving, onClose]);

  const numericFields: [string, string, string][] = [
    [groundLevel, "Ground level", "groundLevel"],
    [groundwaterDepth, "Groundwater depth", "groundwaterDepth"],
    [easting, "Easting", "easting"],
    [northing, "Northing", "northing"],
  ];

  // One result object, not a union. The project compiles with
  // strict:false, so under strictNullChecks being off a `null` branch
  // collapses and a discriminated union loses the narrowing this code
  // depends on. A flat shape with an explicit error field behaves
  // identically under either setting.
  function readNumber(value: string, label: string) {
    if (!value.trim()) {
      return { value: null as number | null, error: null as string | null };
    }

    const parsed = Number(value);

    if (!Number.isFinite(parsed)) {
      return { value: null as number | null, error: `${label} must be a number.` };
    }

    return { value: parsed as number | null, error: null as string | null };
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    if (!projectId) {
      setError("No project ID was provided.");
      return;
    }

    if (!locaId.trim()) {
      setError("Location ID is required.");
      return;
    }

    if (!locaType.trim()) {
      setError("Location type is required.");
      return;
    }

    if (finalDepth && Number(finalDepth) <= 0) {
      setError("Final depth must be greater than zero.");
      return;
    }

    if (groundwaterDepth && Number(groundwaterDepth) < 0) {
      setError("Groundwater depth cannot be negative.");
      return;
    }

    if (startDate && endDate && endDate < startDate) {
      setError("End date cannot be before start date.");
      return;
    }

    const numbers: Record<string, number | null> = {};

    for (const [raw, label, key] of numericFields) {
      const result = readNumber(raw, label);

      if (result.error) {
        setError(result.error);
        return;
      }

      numbers[key] = result.value;
    }

    // AGS stores latitude and longitude as free text, which is what makes
    // degrees/minutes/seconds possible at all. Number() alone would reject
    // DMS with NaN, so a DMS string is converted to its decimal degrees here
    // purely to range-check it, and the text the surveyor typed is what gets
    // stored. Storing the normalised number instead would quietly destroy
    // the original notation, so the raw text is what travels to the database.
    function parseDegrees(value: string): number | null {
      const trimmed = value.trim();

      if (!trimmed) {
        return null;
      }

      // Plain decimal, the common case.
      if (Number.isFinite(Number(trimmed))) {
        return Number(trimmed);
      }

      // Two spellings are accepted. The first needs an explicit degree
      // marker, so "9 55 52" cannot be misread as something else. The second
      // allows bare whitespace but demands all three groups, so it still
      // cannot swallow a stray number.
      const groups =
        trimmed.match(
          /^(-?\d+(?:\.\d+)?)\s*[°d:]\s*(\d+(?:\.\d+)?)?\s*['′m:]?\s*(\d+(?:\.\d+)?)?\s*["″s]?\s*([NSEWnsew])?$/
        ) ||
        trimmed.match(
          /^(-?\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*([NSEWnsew])?$/
        );

      if (!groups) {
        return Number.NaN;
      }

      const degrees = Number(groups[1]);
      const minutes = groups[2] === undefined ? 0 : Number(groups[2]);
      const seconds = groups[3] === undefined ? 0 : Number(groups[3]);
      const hemisphere = groups[4]?.toUpperCase();

      // Minutes and seconds are remainders of a degree, so anything >= 60 is
      // a mistyped value rather than an unusual one.
      if (minutes >= 60 || seconds >= 60) {
        return Number.NaN;
      }

      let decimal = Math.abs(degrees) + minutes / 60 + seconds / 3600;

      if (degrees < 0) {
        decimal = -decimal;
      }

      if (hemisphere === "S" || hemisphere === "W") {
        decimal = -Math.abs(decimal);
      }

      return decimal;
    }

    if (latitude.trim()) {
      const parsedLatitude = parseDegrees(latitude);

      if (!Number.isFinite(parsedLatitude) || Math.abs(parsedLatitude) > 90) {
        setError(
          "Latitude must be decimal degrees (-90 to 90) or degrees, minutes and seconds."
        );
        return;
      }
    }

    if (longitude.trim()) {
      const parsedLongitude = parseDegrees(longitude);

      if (
        !Number.isFinite(parsedLongitude) ||
        Math.abs(parsedLongitude) > 180
      ) {
        setError(
          "Longitude must be decimal degrees (-180 to 180) or degrees, minutes and seconds."
        );
        return;
      }
    }

    try {
      setSaving(true);
      setError(null);

      const created = await createLoca(projectId, {
        loca_id: locaId.trim(),
        loca_type: locaType.trim(),
        start_date: startDate || null,
        end_date: endDate || null,
        final_depth: finalDepth ? Number(finalDepth) : null,
        ground_level: numbers.groundLevel,
        easting: numbers.easting,
        northing: numbers.northing,
        latitude: latitude.trim() || null,
        longitude: longitude.trim() || null,
        groundwater_depth: numbers.groundwaterDepth,
      });

      // Refresh the parent's location list immediately so the new
      // location can be selected without an unrelated page refresh.
      onCreated(created);
      onClose();
    } catch (error) {
      console.error("Failed to create location:", error);

      setError(
        error instanceof Error ? error.message : "Unable to create location."
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        // Only a press on the backdrop itself, not a child that bubbled.
        // mousedown rather than click, so a drag that began inside the
        // dialog and ended outside does not close it.
        if (event.target === event.currentTarget && !saving) onClose();
      }}
    >
      <div className="modal modal-wide">
        <div className="panel-head">
          <h2 className="panel-title">Add Investigation Location</h2>

          <button
            type="button"
            className="btn"
            onClick={onClose}
            disabled={saving}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <form onSubmit={handleSubmit}>
          <div className="panel-body">
            <div className="modal-group">IDENTITY</div>

            <div className="grid grid-2">
              <label>
                <span className="eyebrow">LOCATION ID *</span>
                <input
                  type="text"
                  value={locaId}
                  onChange={(event) => setLocaId(event.target.value)}
                  placeholder="BH-003"
                  autoFocus
                />
              </label>

              <label>
                <span className="eyebrow">LOCATION TYPE *</span>
                <select
                  value={locaType}
                  onChange={(event) => setLocaType(event.target.value)}
                >
                  {LOCA_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="modal-group">DRILLING</div>

            <div className="grid grid-3">
              <label>
                <span className="eyebrow">START DATE</span>
                <input
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                />
              </label>

              <label>
                <span className="eyebrow">END DATE</span>
                <input
                  type="date"
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                />
              </label>

              <label>
                <span className="eyebrow">TERMINATION DEPTH (m)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={finalDepth}
                  onChange={(event) => setFinalDepth(event.target.value)}
                  placeholder="23.45"
                />
              </label>
            </div>

            <div className="modal-group">SURFACE &amp; GROUNDWATER</div>

            <div className="grid grid-2">
              <label>
                <span className="eyebrow">GROUND LEVEL / RL (m)</span>
                <input
                  type="number"
                  step="0.001"
                  value={groundLevel}
                  onChange={(event) => setGroundLevel(event.target.value)}
                  placeholder="3.420"
                />
              </label>

              <label>
                <span className="eyebrow">GROUNDWATER TABLE (m bgl)</span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={groundwaterDepth}
                  onChange={(event) =>
                    setGroundwaterDepth(event.target.value)
                  }
                  placeholder="1.20"
                />
              </label>
            </div>

            <div className="modal-group">COORDINATES</div>

            <div className="grid grid-2">
              <label>
                <span className="eyebrow">EASTING (m)</span>
                <input
                  type="number"
                  step="0.001"
                  value={easting}
                  onChange={(event) => setEasting(event.target.value)}
                  placeholder="384512.235"
                />
              </label>

              <label>
                <span className="eyebrow">NORTHING (m)</span>
                <input
                  type="number"
                  step="0.001"
                  value={northing}
                  onChange={(event) => setNorthing(event.target.value)}
                  placeholder="1098776.412"
                />
              </label>

              <label>
                <span className="eyebrow">LATITUDE</span>
                <input
                  type="text"
                  value={latitude}
                  onChange={(event) => setLatitude(event.target.value)}
                  placeholder="9.9312 or 9°55'52&quot;N"
                />
              </label>

              <label>
                <span className="eyebrow">LONGITUDE</span>
                <input
                  type="text"
                  value={longitude}
                  onChange={(event) => setLongitude(event.target.value)}
                  placeholder="76.2673 or 76°16'02&quot;E"
                />
              </label>
            </div>

            {error && (
              <p className="page-sub field-error">{error}</p>
            )}

            <div className="actions">
              <button
                type="button"
                className="btn"
                onClick={onClose}
                disabled={saving}
              >
                Cancel
              </button>

              <button
                type="submit"
                className="btn btn-primary"
                disabled={saving}
              >
                {saving ? "Adding…" : "Add Location"}
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
