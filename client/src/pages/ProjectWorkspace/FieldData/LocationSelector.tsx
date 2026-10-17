import type { LocaRecord } from "../../../api/projects";

interface LocationSelectorProps {
  locas: LocaRecord[];
  selectedLocaId: string | null;
  onSelectLoca: (locaId: string) => void;
}

export function LocationSelector({
  locas,
  selectedLocaId,
  onSelectLoca,
}: LocationSelectorProps) {
  return (
    <div className="panel">
      <div className="panel-head">
        <h3 className="panel-title">Locations</h3>
      </div>

      <div className="catalog">
        {locas.map((loca) => (
          <button
            key={loca.loca_id}
            type="button"
            className={`item ${selectedLocaId === loca.loca_id ? "active" : ""}`}
            onClick={() => onSelectLoca(loca.loca_id)}
          >
            {loca.loca_id}
          </button>
        ))}
      </div>
    </div>
  );
}
