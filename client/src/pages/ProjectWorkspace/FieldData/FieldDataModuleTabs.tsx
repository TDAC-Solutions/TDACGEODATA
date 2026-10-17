export interface FieldModule {
  id: string;
  label: string;
}

/* "Sampling / Coring" moved to Lab Data as "Sample Register", which is
   project-scoped and can therefore span every borehole at once. What stays
   here is the work: SPT and Rock are the create/edit workflows that generate
   the Sample IDs the register lists. */
export const FIELD_MODULES: FieldModule[] = [
  { id: "overview", label: "Overview" },
  { id: "drilling", label: "Borehole / Drilling" },
  { id: "spt", label: "SPT" },
  { id: "rock", label: "Rock" },
  { id: "groundwater", label: "Groundwater" },
];

interface FieldDataModuleTabsProps {
  activeModule: string;
  onSelectModule: (moduleId: string) => void;
}

export function FieldDataModuleTabs({
  activeModule,
  onSelectModule,
}: FieldDataModuleTabsProps) {
  return (
    <div className="modebar">
      <b>Field Module</b>

      {FIELD_MODULES.map((module) => (
        <button
          key={module.id}
          type="button"
          className={`mode ${activeModule === module.id ? "active" : ""}`}
          onClick={() => onSelectModule(module.id)}
        >
          {module.label}
        </button>
      ))}
    </div>
  );
}
