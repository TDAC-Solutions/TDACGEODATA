/* Static-render smoke test for the new Project Workspace tab components.
   Uses real React (react-dom/server) to actually execute each component
   with mock props, catching runtime errors that syntax-checking alone
   cannot. Mirrors the style of smoke-workspace.test.mjs: no JSX in this
   file (React.createElement only) so it needs no tsconfig/JSX-runtime
   setup, and TSX source files are loaded via the tsx runtime loader. */
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

// apiClient reads a token from localStorage; components fetch on mount.
globalThis.localStorage = {
  getItem: () => "fake-token",
  setItem: () => {},
  removeItem: () => {},
};
globalThis.fetch = async () => ({
  ok: true,
  status: 200,
  json: async () => ({ records: [], available: false, reason: null }),
});

const { PlaceholderPanel } = await import(
  "./src/pages/ProjectWorkspace/PlaceholderPanel.tsx"
);
const { LabData } = await import("./src/pages/ProjectWorkspace/LabData/index.tsx");
const { ProcessedData } = await import(
  "./src/pages/ProjectWorkspace/ProcessedData.tsx"
);
const { InterpretationGroundModel } = await import(
  "./src/pages/ProjectWorkspace/InterpretationGroundModel.tsx"
);
const { DesignParameters } = await import(
  "./src/pages/ProjectWorkspace/DesignParameters.tsx"
);
const { Design } = await import("./src/pages/ProjectWorkspace/Design.tsx");
const { Reports } = await import("./src/pages/ProjectWorkspace/Reports.tsx");
const { Overview } = await import("./src/pages/ProjectWorkspace/Overview.tsx");
const { AddLocaModal } = await import(
  "./src/pages/ProjectWorkspace/AddLocaModal.tsx"
);
const { LocationSelector } = await import(
  "./src/pages/ProjectWorkspace/FieldData/LocationSelector.tsx"
);
const { FieldDataModuleTabs } = await import(
  "./src/pages/ProjectWorkspace/FieldData/FieldDataModuleTabs.tsx"
);
const { BoreholeModule } = await import(
  "./src/pages/ProjectWorkspace/FieldData/BoreholeModule.tsx"
);
const { SptModule } = await import(
  "./src/pages/ProjectWorkspace/FieldData/SptModule.tsx"
);
const { RockModule } = await import(
  "./src/pages/ProjectWorkspace/FieldData/RockModule.tsx"
);
const { GroundwaterModule } = await import(
  "./src/pages/ProjectWorkspace/FieldData/GroundwaterModule.tsx"
);
const { FieldData } = await import(
  "./src/pages/ProjectWorkspace/FieldData/index.tsx"
);

const e = React.createElement;
const results = [];

function check(name, fn) {
  try {
    fn();
    results.push(`PASS ${name}`);
  } catch (err) {
    results.push(`FAIL ${name} -> ${err.message}`);
  }
}

const sampleLoca = {
  loca_id: "BH-01",
  loca_type: "BH",
  final_depth: 30,
  start_date: null,
  end_date: null,
  project_id: "P1",
};

const sampleProject = {
  project_id: "P1",
  project_name: "Test Project",
  project_location: "Test Site",
  project_client: "Test Client",
};

const overviewBaseProps = {
  projectId: "P1",
  onEditingChange: () => {},
  onProjectUpdated: () => {},
  addingLoca: false,
  onAddingLocaChange: () => {},
  onLocaCreated: () => {},
};

check("PlaceholderPanel", () =>
  renderToStaticMarkup(e(PlaceholderPanel, { title: "X" }))
);
check("LabData", () => renderToStaticMarkup(e(LabData)));
check("ProcessedData", () => renderToStaticMarkup(e(ProcessedData)));
check("InterpretationGroundModel", () =>
  renderToStaticMarkup(e(InterpretationGroundModel))
);
check("DesignParameters", () => renderToStaticMarkup(e(DesignParameters)));
check("Design", () => renderToStaticMarkup(e(Design)));
check("Reports", () => renderToStaticMarkup(e(Reports)));

check("Overview (loading)", () =>
  renderToStaticMarkup(
    e(Overview, {
      ...overviewBaseProps,
      project: null,
      loading: true,
      error: null,
      editing: false,
    })
  )
);

check("Overview (loaded, viewing)", () =>
  renderToStaticMarkup(
    e(Overview, {
      ...overviewBaseProps,
      project: sampleProject,
      loading: false,
      error: null,
      editing: false,
    })
  )
);

check("Overview (editing)", () =>
  renderToStaticMarkup(
    e(Overview, {
      ...overviewBaseProps,
      project: sampleProject,
      loading: false,
      error: null,
      editing: true,
    })
  )
);

check("AddLocaModal", () =>
  renderToStaticMarkup(
    e(AddLocaModal, { projectId: "P1", onClose: () => {}, onCreated: () => {} })
  )
);

check("LocationSelector (empty)", () =>
  renderToStaticMarkup(
    e(LocationSelector, { locas: [], selectedLocaId: null, onSelectLoca: () => {} })
  )
);

check("LocationSelector (with data)", () =>
  renderToStaticMarkup(
    e(LocationSelector, {
      locas: [sampleLoca],
      selectedLocaId: "BH-01",
      onSelectLoca: () => {},
    })
  )
);

check("FieldDataModuleTabs", () =>
  renderToStaticMarkup(
    e(FieldDataModuleTabs, { activeModule: "drilling", onSelectModule: () => {} })
  )
);

check("BoreholeModule (initial/loading)", () =>
  renderToStaticMarkup(e(BoreholeModule, { projectId: "P1", locaId: "BH-01" }))
);
check("SptModule (initial/loading)", () =>
  renderToStaticMarkup(e(SptModule, { projectId: "P1", locaId: "BH-01" }))
);
check("RockModule (initial/loading)", () =>
  renderToStaticMarkup(e(RockModule, { projectId: "P1", locaId: "BH-01" }))
);
check("GroundwaterModule (initial/loading)", () =>
  renderToStaticMarkup(e(GroundwaterModule, { projectId: "P1", locaId: "BH-01" }))
);

check("FieldData panel (no locations)", () =>
  renderToStaticMarkup(
    e(FieldData, {
      projectId: "P1",
      locas: [],
      selectedLocaId: null,
      loading: false,
      error: null,
      onSelectLoca: () => {},
      activeModule: "drilling",
      onSelectModule: () => {},
    })
  )
);

check("FieldData panel (with location)", () =>
  renderToStaticMarkup(
    e(FieldData, {
      projectId: "P1",
      locas: [sampleLoca],
      selectedLocaId: "BH-01",
      loading: false,
      error: null,
      onSelectLoca: () => {},
      activeModule: "drilling",
      onSelectModule: () => {},
    })
  )
);

console.log(results.join("\n"));
const failed = results.filter((r) => r.startsWith("FAIL"));
console.log(`\n${results.length - failed.length}/${results.length} passed`);
if (failed.length > 0) {
  process.exit(1);
}
