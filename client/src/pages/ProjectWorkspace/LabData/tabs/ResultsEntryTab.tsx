import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useUnsavedChanges } from "../../UnsavedChanges";
import { useParams } from "react-router-dom";
import {
  getProjectSamples,
  type ProjectSample,
} from "../../../../api/labResults";
import {
  getProjectLabTests,
  getLabTest,
  saveLabRevision,
  reviewLabTest,
  startNewRevision,
  calculateLabTest,
  downloadLabResultPdf,
  isServerCalculated,
  type LabReviewEvent,
  type LabPublicationRecord,
  type LabMethodPin,
  type LabTestDetail,
  type LabTestSummary,
  type ServerCalculationResponse,
} from "../../../../api/lab";
import {
  getLabMethods,
  type LabMethod,
} from "../../../../api/labMethods";
import {
  defaultMethodData,
  evaluate,
  type Evaluation,
  type MethodData,
} from "./resultsEntryEngine";
import {
  HAS_PANEL,
  InputModes,
  MethodPanel,
  PipelineCards,
  ServerCalculationCard,
} from "./ResultsEntryPanels";

type TestType =
  | "PSD"
  | "PARTICLE_DENSITY"
  | "ATTERBERG"
  | "SHRINKAGE_LIMIT"
  | "TRIAXIAL_UU"
  | "CONSOLIDATION";

type AtterbergTab =
  | "liquid"
  | "plastic"
  | "flow"
  | "shrinkage";

type ConsolidationTab =
  | "load"
  | "time"
  | "elog"
  | "cv";

interface TestDefinition {
  id: TestType;
  label: string;
  ags: string;
}

const TESTS: TestDefinition[] = [
  {
    id: "PSD",
    label: "Grain size",
    ags: "GRAG",
  },
  {
    id: "PARTICLE_DENSITY",
    label: "Specific gravity",
    ags: "LPDN",
  },
  {
    id: "ATTERBERG",
    label: "Atterberg limits",
    ags: "LLPL",
  },
  {
    id: "SHRINKAGE_LIMIT",
    label: "Shrinkage limit",
    ags: "LSLT",
  },
  {
    id: "TRIAXIAL_UU",
    label: "Triaxial UU",
    ags: "TRIG",
  },
  {
    id: "CONSOLIDATION",
    label: "Consolidation",
    ags: "CONG",
  },
];

interface IdentityData {
  locationId: string;
  sampleId: string;
  specimenReference: string;
  specimenDepth: string;
  specimenBase: string;
  laboratory: string;
  technician: string;
  testDate: string;
  /**
   * Natural water content of the specimen (%). Atterberg only: when present
   * the server engine additionally reports liquidity and consistency indices.
   */
  naturalWaterContent: string;
}

// Identity starts empty. Every value here is entered by the user or
// copied from a real sample via the samples API - never pre-filled
// with mock values.
const INITIAL_IDENTITY: IdentityData = {
  locationId: "",
  sampleId: "",
  specimenReference: "",
  specimenDepth: "",
  specimenBase: "",
  laboratory: "",
  technician: "",
  testDate: "",
  naturalWaterContent: "",
};

interface LiquidTrial {
  trial: number;
  blows: string;
  container: string;
  containerMass: string;
  wetContainer: string;
  dryContainer: string;
  waterContent: string;
  use: boolean;
}

// Trials start empty. Rows are added by the user while entering a real
// test - no seeded example readings.
const INITIAL_LIQUID_TRIALS: LiquidTrial[] = [];

interface PlasticTrial {
  trial: number;
  container: string;
  containerMass: string;
  wetContainer: string;
  dryContainer: string;
  waterContent: string;
}

const INITIAL_PLASTIC_TRIALS: PlasticTrial[] = [];

/** Label of a method definition exactly as the database holds it. */
function methodLabelOf(method: {
  method_code: string;
  method_version: number;
  standard_reference: string | null;
  standard_edition: string | null;
}): string {
  return [
    method.method_code,
    method.standard_reference,
    method.standard_edition,
    `v${method.method_version}`,
  ]
    .filter((part) => part !== null && part !== undefined && part !== "")
    .join(" · ");
}

/**
 * Reading rows that carry every value their test type requires. Used by the
 * workflow stepper so "Readings" only completes when real readings exist -
 * nothing is assumed from the fact that a test row exists in the database.
 */
function countCompleteReadings(
  test: TestType,
  data: MethodData,
  liquidTrials: LiquidTrial[],
  plasticTrials: PlasticTrial[]
): { complete: number; total: number } {
  const filled = (values: (string | undefined)[]) =>
    values.every((value) => value !== undefined && value.trim() !== "");

  if (test === "ATTERBERG") {
    const liquid = liquidTrials.filter((trial) =>
      filled([trial.blows, trial.containerMass, trial.wetContainer, trial.dryContainer])
    ).length;
    const plastic = plasticTrials.filter((trial) =>
      filled([trial.containerMass, trial.wetContainer, trial.dryContainer])
    ).length;

    return {
      complete: liquid + plastic,
      total: liquidTrials.length + plasticTrials.length,
    };
  }

  const required: Record<TestType, string[]> = {
    PSD: ["size", "tare", "tareRet"],
    PARTICLE_DENSITY: ["m1", "m2", "m3", "m4", "temp"],
    ATTERBERG: [],
    SHRINKAGE_LIMIT: ["wetMass", "dryMass", "wetVol", "dryVol"],
    TRIAXIAL_UU: ["dia", "length", "cell", "q", "strain"],
    CONSOLIDATION: [],
  };

  const columns = required[test];

  return {
    complete: data.rows.filter((row) => filled(columns.map((c) => row[c]))).length,
    total: data.rows.length,
  };
}

// Maps a calculation result label to the released output key stored in the
// revision's calculation_output_snapshot. The keys are the ones each method
// definition declares in lab.method_definition.result_schema, so the release
// step can prove which values it published.
const RESULT_OUTPUT_KEYS: Record<string, string> = {
  "Liquid limit": "liquid_limit",
  "Plastic limit": "plastic_limit",
  "Plasticity index": "plasticity_index",
  "Flow index": "flow_index",
  "Mean cu": "cu",
  "Mean Gs": "specific_gravity",
  "Particle density": "particle_density",
  "Mean shrinkage limit": "shrinkage_limit",
  "Mean shrinkage ratio": "shrinkage_ratio",
};

function outputSummary(results: Evaluation["results"]) {
  const outputs: Record<string, number> = {};

  for (const item of results) {
    const key = RESULT_OUTPUT_KEYS[item.label];
    if (!key) continue;
    const value = Number(item.value);
    if (Number.isFinite(value)) outputs[key] = value;
  }

  return outputs;
}

// Consolidation stages start empty. Stages are added by the user while
// entering a real test - no seeded example stages.
const CONSOLIDATION_STAGES: {
  stage: number;
  direction: string;
  stress: string;
  eStart: string;
  eEnd: string;
  mv: string;
  cvRoot: string;
  cvLog: string;
}[] = [];

export function ResultsEntryTab(
  { selectedTestId }: { selectedTestId: string | null; }
) {
  const [selectedTest, setSelectedTest] =
    useState<TestType>("PSD");

  const [identity, setIdentity] =
    useState<IdentityData>(INITIAL_IDENTITY);

  // No method text is pre-filled: the method profile always comes from the
  // pinned lab.method_definition row, never from a seeded string.
  const [method, setMethod] =
    useState("");

  const [preparation, setPreparation] =
    useState("Wet preparation");

  const [sieveSize, setSieveSize] =
    useState("");

  const [passingSieve, setPassingSieve] =
    useState("");

  const [atterbergTab, setAtterbergTab] =
    useState<AtterbergTab>("liquid");

  const [consolidationTab, setConsolidationTab] =
    useState<ConsolidationTab>("load");

  const [liquidTrials, setLiquidTrials] =
    useState<LiquidTrial[]>(INITIAL_LIQUID_TRIALS);

  const [plasticTrials, setPlasticTrials] =
    useState<PlasticTrial[]>(INITIAL_PLASTIC_TRIALS);

  const { projectId } = useParams();

  const [samples, setSamples] = useState<ProjectSample[]>([]);
  const [methodData, setMethodData] = useState<
    Partial<Record<TestType, MethodData>>
  >({});
  const [evaluation, setEvaluation] = useState<{
    snapshot: string;
    value: Evaluation;
  } | null>(null);
  const [notice, setNotice] = useState("");
  const [revision, setRevision] = useState(1);
  const [audit, setAudit] = useState<string[]>([]);

  // The laboratory test this workbench is editing. Its status is the source
  // of truth for the workflow stepper - not a local editing flag.
  const [labTests, setLabTests] = useState<LabTestSummary[]>([]);
  const [selectedLabTestId, setSelectedLabTestId] = useState("");
  const [testStatus, setTestStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Active method definitions (lab.method_definition) and the full detail of
  // the selected test: pinned method, review events and AGS publications.
  const [methods, setMethods] = useState<LabMethod[]>([]);
  const [dbDetail, setDbDetail] = useState<LabTestDetail | null>(null);

  /*
   * The most recent server calculation (the authoritative numbers). Null
   * until "Calculate (server)" runs or a save returns. For the three
   * engine-backed test types this is what the revision will store, so the
   * card under the workbench always shows the exact values a release would
   * publish -- never the browser preview.
   */
  const [serverCalculation, setServerCalculation] =
    useState<ServerCalculationResponse["calculation_output_snapshot"] | null>(
      null
    );
  const [serverCalculating, setServerCalculating] = useState(false);

  /*
   * Everything a technician types into a test lives in this component and
   * nowhere else. The workspace renders one tab at a time, so leaving Lab
   * Data unmounted this and every unsaved reading went with it, unprompted
   * -- the failure the SPT and Rock grids already guard against, which
   * Results Entry was missing entirely.
   *
   * Dirty means "differs from what was loaded". The baseline is re-taken
   * only when a different test finishes loading, never on a keystroke, so
   * typing does not quietly clear the warning.
   */
  const editableState = useMemo(
    () =>
      JSON.stringify({
        selectedTest,
        identity,
        method,
        preparation,
        sieveSize,
        passingSieve,
        methodData,
        liquidTrials,
        plasticTrials,
      }),
    [
      selectedTest,
      identity,
      method,
      preparation,
      sieveSize,
      passingSieve,
      methodData,
      liquidTrials,
      plasticTrials,
    ]
  );

  const loadedTestRef = useRef<string | null>(null);
  const baselineRef = useRef<string>("");

  // Set when a flow has just restored a test's stored state (chooseLabTest,
  // save, new revision). The baseline must be re-read from the NEXT render,
  // because at the moment the flow sets it, the restored state has not been
  // committed to React yet -- the effect would otherwise pin the baseline to
  // the previous test's leftover readings and either drop the dirty flag or
  // raise a false "unsaved changes" prompt.
  const syncBaselineNextRender = useRef(false);

  useEffect(() => {
    const loadedId = selectedLabTestId || null;
    const isNewTest = loadedId !== loadedTestRef.current;

    if (!isNewTest && !syncBaselineNextRender.current) return;

    loadedTestRef.current = loadedId;
    syncBaselineNextRender.current = false;
    baselineRef.current = editableState;
  }, [selectedLabTestId, dbDetail, editableState]);

  useUnsavedChanges(
    "results-entry",
    "Laboratory Results Entry",
    editableState !== baselineRef.current && !saving
  );

  // Counts test-selection requests so a slow one cannot overwrite a newer
  // choice. Arrow down through the register quickly enough and the responses
  // come back out of order; without this the grid shows the readings of the
  // test you passed two rows ago while the header names the current one.
  const choiceSeq = useRef(0);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    getProjectSamples(projectId)
      .then((data) => {
        if (!cancelled) setSamples(data);
      })
      .catch(() => {
        if (!cancelled) setSamples([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    getProjectLabTests(projectId)
      .then((data) => {
        if (!cancelled) setLabTests(data);
      })
      .catch(() => {
        if (!cancelled) setLabTests([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  useEffect(() => {
    if (!selectedTestId) {
      return;
    }

    if (!labTests.some((test) => test.test_id === selectedTestId)) {
      return;
    }

    chooseLabTest(selectedTestId);
  }, [selectedTestId, labTests]);
  
  // Method profiles are the real active method definitions, so the method
  // fields can never show a standard the database does not know about.
  useEffect(() => {
    getLabMethods()
      .then(setMethods)
      .catch(() => setMethods([]));
  }, []);

  const locationOptions = Array.from(
    new Set(samples.map((sample) => sample.loca_id))
  );
  const sampleOptions = samples.filter(
    (sample) => sample.loca_id === identity.locationId
  );

  // Laboratories and technicians come from the laboratory tests this project
  // actually has, unioned with whatever the loaded snapshot stores: a value
  // copied from a legacy revision must render in the select, not read as
  // blank.
  const laboratoryOptions = Array.from(
    new Set(
      [
        identity.laboratory || null,
        ...labTests
          .map((test) => test.laboratory)
          .filter((value): value is string => !!value && value.trim() !== ""),
      ].filter((value): value is string => !!value)
    )
  ).sort();

  const technicianOptions = Array.from(
    new Set(
      [
        identity.technician || null,
        ...labTests
          .map((test) => test.technician)
          .filter((value): value is string => !!value && value.trim() !== ""),
      ].filter((value): value is string => !!value)
    )
  ).sort();

  function chooseLocation(locationId: string) {
    const first = samples.find((sample) => sample.loca_id === locationId);
    setIdentity((previous) => ({
      ...previous,
      locationId,
      sampleId: first ? first.sample_id : previous.sampleId,
      specimenDepth: first ? String(first.depth_from) : previous.specimenDepth,
      specimenBase:
        first && first.depth_to !== null ? String(first.depth_to) : previous.specimenBase,
    }));
  }

  function chooseSample(sampleId: string) {
    const found = samples.find((sample) => sample.sample_id === sampleId);
    setIdentity((previous) => ({
      ...previous,
      sampleId,
      specimenDepth: found ? String(found.depth_from) : previous.specimenDepth,
      specimenBase:
        found && found.depth_to !== null ? String(found.depth_to) : previous.specimenBase,
    }));
  }

  const currentData: MethodData =
    selectedTest === "ATTERBERG"
      ? {
          params: {},
          rows: liquidTrials.map((trial) => ({
            blows: trial.blows,
            container: trial.container,
            containerMass: trial.containerMass,
            wetContainer: trial.wetContainer,
            dryContainer: trial.dryContainer,
            use: String(trial.use),
          })),
          rows2: plasticTrials.map((trial) => ({
            container: trial.container,
            containerMass: trial.containerMass,
            wetContainer: trial.wetContainer,
            dryContainer: trial.dryContainer,
          })),
        }
      : methodData[selectedTest] ?? defaultMethodData(selectedTest);

  const snapshot = useMemo(
    () => selectedTest + JSON.stringify(currentData),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selectedTest, methodData, liquidTrials, plasticTrials]
  );
  const stale = evaluation !== null && evaluation.snapshot !== snapshot;
  const calculated = evaluation !== null && !stale;

  // ---------------------------------------------------------------------
  // Workflow stepper state.
  //
  // Every one of the six steps is derived from something that really exists:
  //   Identity    - the identity fields the user has actually entered
  //   Method      - the method definition pinned on the registered test
  //   Readings    - reading rows that carry all their required values
  //   Calculation - the stored lab.test_revision of the current revision
  //   QA          - the real lab.test.status (SUBMITTED/CHECKED/APPROVED)
  //   Release     - the AGS publication records of this revision
  //
  // No step is pre-lit. With no test selected, or with empty identity or
  // readings, those steps stay pending, and the first unfinished step is the
  // only active one.
  // ---------------------------------------------------------------------
  const workflowStatus = testStatus ?? "";
  const hasTest = selectedLabTestId !== "";

  const identityValues = [
    identity.locationId,
    identity.sampleId,
    identity.specimenReference,
    identity.laboratory,
    identity.testDate,
  ];
  const identityFilled = identityValues.filter(
    (value) => value.trim() !== ""
  ).length;
  const identityDone = identityFilled === identityValues.length;

  const pinnedMethod: LabMethodPin | null = dbDetail?.method ?? null;
  const methodDone = pinnedMethod !== null;

  const readings = countCompleteReadings(
    selectedTest,
    currentData,
    liquidTrials,
    plasticTrials
  );
  const readingsDone = readings.complete > 0;

  const reviewEvents: LabReviewEvent[] = dbDetail?.review_events ?? [];
  const publication: LabPublicationRecord[] = dbDetail?.publication ?? [];

  const revisionStored = dbDetail?.revision !== null && dbDetail?.revision !== undefined;
  const calculationStored =
    revisionStored && dbDetail?.revision?.calculation_output_snapshot != null;
  const calcDone = hasTest && calculationStored;
  const qaActive = hasTest && ["SUBMITTED", "CHECKED"].includes(workflowStatus);
  const qaDone =
    hasTest && ["APPROVED", "PUBLISHED"].includes(workflowStatus);
  const releaseActive = hasTest && workflowStatus === "APPROVED";
  const releaseDone = hasTest && workflowStatus === "PUBLISHED";

  // Method profiles available for the test type of the current workbench.
  const methodOptions = methods
    .filter((entry) => entry.test_type === selectedTest)
    .map(methodLabelOf);

  const workflowSteps: {
    number: string;
    label: string;
    done: boolean;
    caption: string;
    hint: string;
  }[] = [
    {
      number: "1",
      label: "Identity",
      done: identityDone,
      caption: `${identityFilled}/${identityValues.length} identity fields`,
      hint: `Common test identity: project, location, sample and specimen. ${identityFilled} of ${identityValues.length} fields are entered.`,
    },
    {
      number: "2",
      label: "Method",
      done: methodDone,
      caption: pinnedMethod
        ? methodLabelOf(pinnedMethod)
        : "No method pinned on a test",
      hint: pinnedMethod
        ? `Pinned method: ${pinnedMethod.method_name} (${pinnedMethod.calculation_package} ${pinnedMethod.calculation_package_version}).`
        : "Select a registered laboratory test: its method definition is pinned when the test is registered.",
    },
    {
      number: "3",
      label: "Readings",
      done: readingsDone,
      caption: readings.total
        ? `${readings.complete}/${readings.total} row(s) complete`
        : "No readings entered",
      hint: "Test-specific raw readings stored in this revision. A row counts once every required value is entered.",
    },
    {
      number: "4",
      label: "Calculation",
      done: calcDone,
      caption: revisionStored
        ? `Revision ${dbDetail?.revision?.revision_no} stored`
        : calculated
        ? "Calculated locally, not stored"
        : "Not calculated",
      hint: "Recalculate from the entered readings, then Save draft to store the revision in the database.",
    },
    {
      number: "5",
      label: "QA",
      done: qaDone,
      caption: qaDone
        ? `Approved (${workflowStatus})`
        : qaActive
        ? `In review (${workflowStatus})`
        : "Awaiting submission",
      hint: "Independent check and approval happen on the QA and Approval tab.",
    },
    {
      number: "6",
      label: "Release",
      done: releaseDone,
      caption: releaseDone
        ? `${publication.length} AGS publication record(s)`
        : releaseActive
        ? "Approved, not released"
        : "Awaiting approval",
      hint: "Publish writes the approved values to the AGS publication record; only then is the revision PUBLISHED.",
    },
  ];

  const activeStepIndex = workflowSteps.findIndex((step) => !step.done);

  function updateIdentity(
    field: keyof IdentityData,
    value: string
  ) {
    setIdentity((previous) => ({
      ...previous,
      [field]: value,
    }));
  }

  function handleTestChange(test: TestType) {
    setSelectedTest(test);
    // The method profile belongs to the registered test, so switching the
    // workbench test type clears the field instead of inventing a standard.
    setMethod("");
  }

  function updateLiquidTrial(
    trialNumber: number,
    field: keyof LiquidTrial,
    value: string | boolean
  ) {
    setLiquidTrials((previous) =>
      previous.map((trial) =>
        trial.trial === trialNumber
          ? {
              ...trial,
              [field]: value,
            }
          : trial
      )
    );
  }

  function updatePlasticTrial(
    trialNumber: number,
    field: keyof PlasticTrial,
    value: string
  ) {
    setPlasticTrials((previous) =>
      previous.map((trial) =>
        trial.trial === trialNumber
          ? {
              ...trial,
              [field]: value,
            }
          : trial
      )
    );
  }

  // Trials are added and removed by the user against a real test. Nothing
  // is seeded, so the flow curve only ever plots entered readings.
  function addLiquidTrial() {
    setLiquidTrials((previous) => [
      ...previous,
      {
        trial: previous.length + 1,
        blows: "",
        container: `LL-${previous.length + 1}`,
        containerMass: "",
        wetContainer: "",
        dryContainer: "",
        waterContent: "",
        use: true,
      },
    ]);
  }

  function removeLiquidTrial(trialNumber: number) {
    setLiquidTrials((previous) =>
      previous
        .filter((trial) => trial.trial !== trialNumber)
        .map((trial, index) => ({ ...trial, trial: index + 1 }))
    );
  }

  function addPlasticTrial() {
    setPlasticTrials((previous) => [
      ...previous,
      {
        trial: previous.length + 1,
        container: `PL-${previous.length + 1}`,
        containerMass: "",
        wetContainer: "",
        dryContainer: "",
        waterContent: "",
      },
    ]);
  }

  function removePlasticTrial(trialNumber: number) {
    setPlasticTrials((previous) =>
      previous
        .filter((trial) => trial.trial !== trialNumber)
        .map((trial, index) => ({ ...trial, trial: index + 1 }))
    );
  }

  function runEvaluation() {
    const value = evaluate(selectedTest, currentData);
    setEvaluation({ snapshot, value });
    return value;
  }

  function logAudit(entry: string) {
    setAudit((previous) => [
      `${new Date().toLocaleTimeString()} · rev ${revision} · ${entry}`,
      ...previous,
    ]);
  }

  // The stepper is a jump-to-section control: each step scrolls the workbench
  // to the panel it refers to. QA/Release live on the QA and Approval tab, so
  // those steps explain where the action happens.
  function goToStep(step: number) {
    if (step === 5 || step === 6) {
      setNotice(
        step === 5
          ? "Independent checking happens on the QA and Approval tab: Submit for check records SUBMITTED, Mark checked records CHECKED, Approve records APPROVED."
          : "Release is a separate action: Publish writes the approved values to the AGS publication record and only then does the revision become PUBLISHED."
      );
      return;
    }

    const target =
      step <= 2
        ? "re-section-identity"
        : step === 3
        ? "re-section-readings"
        : "re-section-validation";

    document
      .getElementById(target)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  // Restore the workbench from a stored raw-input snapshot.
  function applyRawSnapshot(
    raw: Record<string, unknown> | null | undefined,
    testType: string
  ) {
    const snapshot = (raw ?? {}) as Record<string, any>;

    // Reset first. The old early-return on a missing snapshot left the
    // previous test's trials on screen -- and, because the baseline effect
    // pinned them for the newly selected test, they read as "clean". A save
    // then wrote the old test's readings into the new test's revision.
    setEvaluation(null);
    setLiquidTrials(INITIAL_LIQUID_TRIALS);
    setPlasticTrials(INITIAL_PLASTIC_TRIALS);
    setMethodData({});

    if (snapshot.identity) {
      setIdentity((previous) => ({ ...previous, ...snapshot.identity }));
    }
    if (typeof snapshot.method === "string") setMethod(snapshot.method);
    if (typeof snapshot.preparation === "string")
      setPreparation(snapshot.preparation);
    if (typeof snapshot.sieveSize === "string")
      setSieveSize(snapshot.sieveSize);
    if (typeof snapshot.passingSieve === "string")
      setPassingSieve(snapshot.passingSieve);

    const data = snapshot.data as MethodData | undefined;

    if (testType === "ATTERBERG") {
      setLiquidTrials(
        (data?.rows ?? []).map((row, index) => ({
          trial: index + 1,
          blows: String(row.blows ?? ""),
          container: String(row.container ?? ""),
          containerMass: String(row.containerMass ?? ""),
          wetContainer: String(row.wetContainer ?? ""),
          dryContainer: String(row.dryContainer ?? ""),
          waterContent: "",
          use: row.use !== "false",
        }))
      );
      setPlasticTrials(
        (data?.rows2 ?? []).map((row, index) => ({
          trial: index + 1,
          container: String(row.container ?? ""),
          containerMass: String(row.containerMass ?? ""),
          wetContainer: String(row.wetContainer ?? ""),
          dryContainer: String(row.dryContainer ?? ""),
          waterContent: "",
        }))
      );
      return;
    }

    if (data) {
      setMethodData((previous) => ({
        ...previous,
        [testType as TestType]: data,
      }));
    }
  }

  async function chooseLabTest(testId: string) {
    const seq = ++choiceSeq.current;
    setSelectedLabTestId(testId);
    setNotice("");

    // The card below the workbench shows one test's server numbers; a
    // different test's numbers must never survive the switch. Cleared here
    // and repopulated only by a calculate/save against the new selection.
    setServerCalculation(null);

    if (!testId || !projectId) {
      setTestStatus(null);
      setDbDetail(null);
      return;
    }

    try {
      setSaving(true);
      const detail = await getLabTest(projectId, testId);

      // A newer selection was made while this one was in flight; its response
      // is the one the user is waiting for.
      if (seq !== choiceSeq.current) return;

      const summary = labTests.find((test) => test.test_id === testId);

      // Identity and method now come from the registered test row, not from
      // placeholder values. The specimen depth/base belong to the sample the
      // test was registered against, so they are restored from the summary
      // too -- otherwise they kept the previously selected sample's depths
      // while the header named the new one.
      setSelectedTest(detail.test_type as TestType);
      setTestStatus(detail.status);
      setRevision(detail.current_revision);
      setDbDetail(detail);
      setIdentity((previous) => ({
        ...previous,
        locationId: detail.loca_id,
        sampleId: detail.sample_id,
        specimenReference: detail.spec_ref ?? "",
        specimenDepth:
          summary?.samp_top != null
            ? String(summary.samp_top)
            : previous.specimenDepth,
        specimenBase:
          summary?.samp_base != null
            ? String(summary.samp_base)
            : previous.specimenBase,
        laboratory: summary?.laboratory ?? previous.laboratory,
        technician: summary?.technician ?? previous.technician,
        testDate: summary?.created_at
          ? summary.created_at.slice(0, 10)
          : previous.testDate,
      }));
      setMethod(detail.method ? methodLabelOf(detail.method) : "");
      applyRawSnapshot(detail.revision?.raw_input_snapshot, detail.test_type);

      // If this revision already stores a server calculation, show it: the
      // card below the workbench must agree with what QA will read, and the
      // cleared card made a calculated test look uncalculated after a
      // reload.
      if (
        isServerCalculated(detail.test_type) &&
        detail.revision?.calculation_output_snapshot
      ) {
        setServerCalculation(
          detail.revision
            .calculation_output_snapshot as ServerCalculationResponse["calculation_output_snapshot"]
        );
      }

      // The restored readings are a fresh, clean baseline for this test; the
      // effect re-reads it on the next render after all the setters above
      // have been committed.
      syncBaselineNextRender.current = true;

      setNotice(
        `Loaded ${detail.test_id.slice(0, 8)} · ${detail.status} · revision ${detail.current_revision}.`
      );
    } catch (err) {
      // A failed load must not leave a dead test id armed for the next Save:
      // the user would silently write against a test that no longer exists.
      if (seq === choiceSeq.current) {
        setSelectedLabTestId("");
        setTestStatus(null);
        setDbDetail(null);
        setRevision(1);
        setServerCalculation(null);
      }
      setNotice(
        err instanceof Error ? err.message : "Could not load that test."
      );
    } finally {
      setSaving(false);
    }
  }

  function buildRevisionPayload(value: Evaluation) {
    return {
      raw_input_snapshot: {
        identity,
        method,
        preparation,
        sieveSize,
        passingSieve,
        data: currentData,
      },
      calculation_output_snapshot: {
        outputs: outputSummary(value.results),
        results: value.results,
        curve: value.curve ?? null,
        perRow: value.perRow ?? null,
        ags: value.ags ?? null,
      },
      validation_snapshot: {
        issues: value.issues,
        errors: value.issues.filter((issue) => issue.level === "error").length,
        warnings: value.issues.filter((issue) => issue.level === "warning")
          .length,
      },
      revision_reason: "Calculated draft",
    };
  }

  async function handleSaveDraft() {
    if (!projectId) {
      setNotice("No project in context: draft not saved.");
      return;
    }
    if (!selectedLabTestId) {
      setNotice("Select a registered laboratory test before saving.");
      return;
    }

    const value = evaluation && !stale ? evaluation.value : runEvaluation();

    try {
      setSaving(true);
      // Same rule as submit: for engine-backed test types the server
      // recomputes from the raw readings, so only the raw snapshot travels.
      const saved = await saveLabRevision(
        projectId,
        selectedLabTestId,
        isServerCalculated(selectedTest)
          ? { raw_input_snapshot: buildRawSnapshot() }
          : buildRevisionPayload(value)
      );
      setTestStatus(saved.status);
      setRevision(saved.current_revision);
      setDbDetail(saved);

      // For engine-backed test types the server recomputed the calculation
      // before storing it, so what came back is the authoritative snapshot.
      // Show that, not the browser preview, or the card would disagree with
      // what QA and the release step actually read.
      if (isServerCalculated(saved.test_type) && saved.revision?.calculation_output_snapshot) {
        setServerCalculation(
          saved.revision.calculation_output_snapshot as ServerCalculationResponse["calculation_output_snapshot"]
        );
      }

      setNotice(
        `Draft saved to the server · status ${saved.status} · revision ${saved.current_revision}.`
      );
      logAudit("draft saved to server");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Draft could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  function handleCalculate() {
    const value = runEvaluation();
    const errors = value.issues.filter((issue) => issue.level === "error").length;
    setNotice(
      errors
        ? `Calculated with ${errors} blocking error(s).`
        : "Calculated and validated."
    );
    logAudit("calculated/validated");
  }

  /**
   * Run the authoritative server engine without saving. For the three
   * engine-backed test types this is the exact snapshot a save will store,
   * so the technician sees the released numbers before committing. For the
   * other test types it explains there is no server engine (the local
   * preview remains the only calculation) instead of silently doing less
   * than the button promises.
   */
  async function handleServerCalculate() {
    if (!projectId || !selectedLabTestId) {
      setNotice("Select a registered laboratory test first.");
      return;
    }
    if (!isServerCalculated(selectedTest)) {
      setNotice(
        `${selectedTest} is calculated by the local preview engine only; the server engine covers PSD, PARTICLE_DENSITY and ATTERBERG.`
      );
      return;
    }

    try {
      setServerCalculating(true);
      setNotice("Calculating on the server…");
      const response = await calculateLabTest(
        projectId,
        selectedLabTestId,
        buildRawSnapshot()
      );
      setServerCalculation(response.calculation_output_snapshot);
      const warnings = response.validation_snapshot.warnings;
      setNotice(
        warnings === 0
          ? "Server calculation complete; no warnings."
          : `Server calculation complete with ${warnings} warning(s).`
      );
      logAudit("server calculation");
    } catch (err) {
      setServerCalculation(null);
      setNotice(
        err instanceof Error
          ? `Server calculation failed: ${err.message}`
          : "Server calculation failed."
      );
    } finally {
      setServerCalculating(false);
    }
  }

  /**
   * "Start new revision" for a locked (APPROVED/PUBLISHED/RETURNED) test:
   * the old revision stays as the immutable released record, a fresh DRAFT
   * revision opens with the readings carried forward.
   */
  async function handleStartNewRevision() {
    if (!projectId || !selectedLabTestId) return;

    try {
      setSaving(true);
      const detail = await startNewRevision(projectId, selectedLabTestId);
      setTestStatus(detail.status);
      setRevision(detail.current_revision);
      setDbDetail(detail);
      applyRawSnapshot(detail.revision?.raw_input_snapshot, detail.test_type);
      setServerCalculation(null); // new revision has no calc snapshot yet
      setNotice(
        `New revision ${detail.current_revision} opened. Recalculate and save to proceed.`
      );
      logAudit(`new revision ${detail.current_revision} started`);
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Could not start a new revision.");
    } finally {
      setSaving(false);
    }
  }

  /** Download the DRAFT-stamped result sheet rendered from the stored revision. */
  async function handleDownloadResultPdf() {
    if (!projectId || !selectedLabTestId) {
      setNotice("Select a registered laboratory test first.");
      return;
    }
    if (!isServerCalculated(selectedTest)) {
      setNotice(
        "Result sheets are rendered by the server engine for PSD, PARTICLE_DENSITY and ATTERBERG tests."
      );
      return;
    }

    try {
      setNotice("Generating result sheet…");
      await downloadLabResultPdf(projectId, selectedLabTestId);
      setNotice("Result sheet downloaded.");
      logAudit("result sheet downloaded");
    } catch (err) {
      setNotice(
        err instanceof Error ? err.message : "Could not generate the result sheet."
      );
    }
  }

  /**
   * The raw snapshot exactly as saveRevisionPayload builds it, for the
   * server's dry-run calculate. Same shape on the wire, so the preview and
   * the save can never disagree about what was entered.
   */
  function buildRawSnapshot() {
    return {
      identity,
      method,
      preparation,
      sieveSize,
      passingSieve,
      data: currentData,
    };
  }

  async function handleSubmit() {
    if (!projectId || !selectedLabTestId) {
      setNotice("Select a registered laboratory test before submitting.");
      return;
    }

    const value = runEvaluation();
    const errors = value.issues.filter((issue) => issue.level === "error").length;
    if (errors) {
      setNotice(`Cannot submit: ${errors} blocking error(s) — see Validation.`);
      return;
    }

    try {
      setSaving(true);
      // Persist the current readings, then advance the real status.
      // For engine-backed test types the server recomputes the calculation
      // from these raw readings, so sending the browser's calculation
      // snapshot would be dead weight on the wire and misleading to anyone
      // reading the request body -- the raw snapshot alone is the contract.
      const saved = await saveLabRevision(
        projectId,
        selectedLabTestId,
        isServerCalculated(selectedTest)
          ? { raw_input_snapshot: buildRawSnapshot() }
          : buildRevisionPayload(value)
      );

      // The save is committed even if the submit below fails. Sync the
      // header/stepper to it first; otherwise a failed submit left the UI
      // claiming the pre-save status while the database held CALCULATED.
      setTestStatus(saved.status);
      setRevision(saved.current_revision);
      setDbDetail(saved);
      if (
        isServerCalculated(saved.test_type) &&
        saved.revision?.calculation_output_snapshot
      ) {
        setServerCalculation(
          saved.revision
            .calculation_output_snapshot as ServerCalculationResponse["calculation_output_snapshot"]
        );
      }

      const submitted = await reviewLabTest(
        projectId,
        selectedLabTestId,
        "submit"
      );
      setTestStatus(submitted.status);
      setRevision(submitted.current_revision);
      setDbDetail(submitted);
      // The submit response carries the server's stored snapshot; show it.
      if (
        isServerCalculated(submitted.test_type) &&
        submitted.revision?.calculation_output_snapshot
      ) {
        setServerCalculation(
          submitted.revision
            .calculation_output_snapshot as ServerCalculationResponse["calculation_output_snapshot"]
        );
      }
      setNotice("Submitted for independent checking.");
      logAudit("submitted for check");
    } catch (err) {
      setNotice(err instanceof Error ? err.message : "Submit failed.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="results-entry">

      {/* =====================================================
          PAGE HEADER
          ===================================================== */}

      <div className="results-entry-header">

        <div className="results-entry-header-left">

          <div className="results-entry-eyebrow">
            LABORATORY WORKBENCH
          </div>

          <h1 className="results-entry-title">
            Results Entry
          </h1>

          <p className="results-entry-description">
            The common header stays identical for every
            method. Test-specific raw readings,
            calculations, validation and AGS mapping are
            driven by the selected method definition.
          </p>

        </div>

        <div className="results-entry-actions">

          <button
            type="button"
            onClick={handleSaveDraft}
            disabled={saving || serverCalculating}
          >
            {saving ? "Saving…" : "Save draft"}
          </button>

          <button
            type="button"
            onClick={handleCalculate}
            disabled={saving || serverCalculating}
          >
            Calculate and validate
          </button>

          {/* Server engine: the authoritative numbers for the three
              engine-backed test types (preview-only for everything else). */}
          <button
            type="button"
            onClick={handleServerCalculate}
            disabled={saving || serverCalculating || !isServerCalculated(selectedTest)}
            title={
              isServerCalculated(selectedTest)
                ? "Run the authoritative server engine without saving"
                : "No server engine for this test type; the local preview is the calculation"
            }
          >
            {serverCalculating ? "Calculating…" : "Calculate (server)"}
          </button>

          {/* DRAFT-stamped result sheet, rendered by the server engine from
              the stored revision (available once a revision is saved). */}
          <button
            type="button"
            onClick={handleDownloadResultPdf}
            disabled={saving || serverCalculating || !isServerCalculated(selectedTest)}
            title="Download the DRAFT method result sheet for the stored revision"
          >
            Result sheet PDF
          </button>

          <button
            type="button"
            className="primary-action"
            onClick={handleSubmit}
            disabled={saving || serverCalculating}
          >
            Submit for check
          </button>

          {/* Locked revisions (approved, published, or returned) are a dead
              end without this: the unique key forbids re-registering the
              same sample+type. Only shown when one is actually locked. */}
          {hasTest && ["APPROVED", "PUBLISHED", "RETURNED"].includes(
            workflowStatus
          ) && (
            <button
              type="button"
              onClick={handleStartNewRevision}
              disabled={saving || serverCalculating}
              title="Open a new editable revision that supersedes the locked one"
            >
              Start new revision
            </button>
          )}

        </div>

      </div>

      {/* =====================================================
          WORKFLOW
          ===================================================== */}

      <div className="results-workflow">

        {/* One card per controlled stage. Each card is fed by the workflowSteps
            state above: done from real data/database state, active for the one
            stage that is currently being worked on, pending for the stages that
            are not reached yet. */}
        {workflowSteps.map((step, index) => (
          <WorkflowItem
            key={step.number}
            number={step.number}
            label={step.label}
            active={index === activeStepIndex}
            done={step.done}
            pending={index > activeStepIndex && activeStepIndex !== -1}
            caption={step.caption}
            hint={step.hint}
            onClick={() => goToStep(Number(step.number))}
          />
        ))}

      </div>

      {/* =====================================================
          MAIN LAYOUT
          ===================================================== */}

      <div className="results-entry-layout">

        {/* ===================================================
            TEST CATALOG
            =================================================== */}

        <aside className="catalog">

          {TESTS.map((test) => {

            const active =
              selectedTest === test.id;

            return (
              <button
                key={test.id}
                type="button"
                className={`item ${active ? "active" : ""}`}
                onClick={() =>
                  handleTestChange(test.id)
                }
              >

                <span>
                  {test.label}
                </span>

                <span className="catalog-ags">
                  {test.ags}
                </span>

              </button>
            );
          })}

        </aside>

        {/* ===================================================
            RIGHT CONTENT
            =================================================== */}

        <main className="results-main">

          <InputModes />

          {/* =================================================
              COMMON IDENTITY
              ================================================= */}

          <section className="results-card" id="re-section-identity">

            <div className="results-card-header">

              <div>
                <h2>
                  Common test identity
                </h2>
              </div>

              <div className="revision-badge">
                {hasTest ? `${workflowStatus} · ` : ""}Revision {revision}
              </div>

            </div>

            <div className="identity-grid">

              <Field label="Laboratory test">

                <select
                  value={selectedLabTestId}
                  onChange={(event) =>
                    chooseLabTest(event.target.value)
                  }
                >
                  <option value="">
                    Select a registered test…
                  </option>

                  {labTests.map((test) => (
                    <option key={test.test_id} value={test.test_id}>
                      {test.loca_id} · {test.samp_id} · {test.spec_ref ?? "—"} ·{" "}
                      {test.test_type} · {test.status}
                    </option>
                  ))}
                </select>

              </Field>

              <Field label="Location ID">

                <select
                  value={identity.locationId}
                  onChange={(event) =>
                    chooseLocation(event.target.value)
                  }
                >
                  {locationOptions.length ? (
                    locationOptions.map((id) => (
                      <option key={id}>{id}</option>
                    ))
                  ) : (
                    <option value="">
                      No locations for this project
                    </option>
                  )}
                </select>

              </Field>

              <Field label="Sample ID">

                <select
                  value={identity.sampleId}
                  onChange={(event) =>
                    chooseSample(event.target.value)
                  }
                >
                  {sampleOptions.length ? (
                    sampleOptions.map((sample) => (
                      <option key={sample.sample_id}>
                        {sample.sample_id}
                      </option>
                    ))
                  ) : (
                    <option value="">
                      No samples for this location
                    </option>
                  )}
                </select>

              </Field>

              <Field label="Specimen reference">

                <input
                  value={identity.specimenReference}
                  onChange={(event) =>
                    updateIdentity(
                      "specimenReference",
                      event.target.value
                    )
                  }
                />

              </Field>

              <Field label="Specimen depth (m)">

                <input
                  value={identity.specimenDepth}
                  onChange={(event) =>
                    updateIdentity(
                      "specimenDepth",
                      event.target.value
                    )
                  }
                />

              </Field>

              <Field label="Specimen base (m)">

                <input
                  value={identity.specimenBase}
                  onChange={(event) =>
                    updateIdentity(
                      "specimenBase",
                      event.target.value
                    )
                  }
                />

              </Field>

              <Field label="Laboratory">

                <select
                  value={identity.laboratory}
                  onChange={(event) =>
                    updateIdentity(
                      "laboratory",
                      event.target.value
                    )
                  }
                >

                  {/* Laboratories recorded on this project's laboratory tests.
                      No placeholder laboratory is offered: with none recorded
                      the field simply has nothing to choose from. */}
                  {laboratoryOptions.length === 0 && (
                    <option value="">
                      No laboratory recorded for this project
                    </option>
                  )}

                  {laboratoryOptions.map((laboratory) => (
                    <option key={laboratory} value={laboratory}>
                      {laboratory}
                    </option>
                  ))}

                </select>

              </Field>

              <Field label="Technician">

                <select
                  value={identity.technician}
                  onChange={(event) =>
                    updateIdentity(
                      "technician",
                      event.target.value
                    )
                  }
                >

                  {/* Technicians recorded on this project's laboratory tests. */}
                  {technicianOptions.length === 0 && (
                    <option value="">
                      No technician recorded for this project
                    </option>
                  )}

                  {technicianOptions.map((technician) => (
                    <option key={technician} value={technician}>
                      {technician}
                    </option>
                  ))}

                </select>

              </Field>

              <Field label="Test date">

                <input
                  type="date"
                  value={identity.testDate}
                  onChange={(event) =>
                    updateIdentity(
                      "testDate",
                      event.target.value
                    )
                  }
                />

              </Field>

            </div>

          </section>

          {/* =================================================
              TEST SPECIFIC
              ================================================= */}

          <div id="re-section-readings" />

          {selectedTest === "ATTERBERG" && (

            <AtterbergSection
              method={method}
              methodOptions={methodOptions}
              preparation={preparation}
              sieveSize={sieveSize}
              passingSieve={passingSieve}
              naturalWaterContent={identity.naturalWaterContent}
              atterbergTab={atterbergTab}
              setMethod={setMethod}
              setPreparation={setPreparation}
              setSieveSize={setSieveSize}
              setPassingSieve={setPassingSieve}
              setNaturalWaterContent={(value) =>
                updateIdentity("naturalWaterContent", value)
              }
              setAtterbergTab={setAtterbergTab}
              liquidTrials={liquidTrials}
              plasticTrials={plasticTrials}
              updateLiquidTrial={updateLiquidTrial}
              updatePlasticTrial={updatePlasticTrial}
              addLiquidTrial={addLiquidTrial}
              removeLiquidTrial={removeLiquidTrial}
              addPlasticTrial={addPlasticTrial}
              removePlasticTrial={removePlasticTrial}
              evaluation={
                selectedTest === "ATTERBERG"
                  ? evaluation?.value ?? null
                  : null
              }
            />

          )}

          {selectedTest === "CONSOLIDATION" && (

            <ConsolidationSection
              method={method}
              methodOptions={methodOptions}
              setMethod={setMethod}
              consolidationTab={consolidationTab}
              setConsolidationTab={
                setConsolidationTab
              }
            />

          )}

          {HAS_PANEL.includes(selectedTest) && (
              <MethodPanel
                test={selectedTest}
                data={currentData}
                methodOptions={methodOptions}
                onChange={(next) =>
                  setMethodData((previous) => ({
                    ...previous,
                    [selectedTest]: next,
                  }))
                }
              />
            )}

          <div id="re-section-validation" />

          <PipelineCards
            test={selectedTest}
            evaluation={evaluation ? evaluation.value : null}
            stale={stale}
            notice={notice}
          />

          {/* The authoritative numbers for engine-backed test types. */}
          <ServerCalculationCard
            calculation={serverCalculation}
            preview={calculated ? evaluation?.value ?? null : null}
          />

          {/* Real review history from lab.review_event for the selected test,
              plus the AGS publication records written by the release step. */}
          {hasTest && (
            <section className="results-card">
              <div className="results-card-header">
                <h2>Review events and publication</h2>
                <span className="ags-label">
                  AGS&nbsp;&nbsp;
                  {(dbDetail?.ags_groups ?? []).join(" + ") || "not mapped"}
                </span>
              </div>

              {reviewEvents.length === 0 ? (
                <p className="re-muted">
                  No review event recorded for this test yet.
                </p>
              ) : (
                <div className="table-scroll">
                  <table className="results-table">
                    <thead>
                      <tr>
                        <th>Event</th>
                        <th>Transition</th>
                        <th>Actor</th>
                        <th>Role</th>
                        <th>Reason</th>
                        <th>When</th>
                      </tr>
                    </thead>
                    <tbody>
                      {reviewEvents.map((event, index) => (
                        <tr key={`${event.event_type}-${index}`}>
                          <td>{event.event_type}</td>
                          <td>
                            {event.from_status ?? "—"} → {event.to_status}
                          </td>
                          <td>{event.actor}</td>
                          <td>{event.actor_role}</td>
                          <td>{event.reason ?? "—"}</td>
                          <td>{new Date(event.event_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {publication.length === 0 ? (
                <p className="re-muted">
                  Not published. Release writes one AGS publication record per
                  AGS group of the pinned method after approval.
                </p>
              ) : (
                <div className="table-scroll">
                  <table className="results-table">
                    <thead>
                      <tr>
                        <th>AGS group</th>
                        <th>Rows</th>
                        <th>Record hash</th>
                        <th>Status</th>
                        <th>Published by</th>
                        <th>Published at</th>
                      </tr>
                    </thead>
                    <tbody>
                      {publication.map((record) => (
                        <tr key={record.ags_group}>
                          <td>{record.ags_group}</td>
                          <td>{record.projected_row_count}</td>
                          <td className="re-mono">
                            {record.projected_row_hash.slice(0, 16)}…
                          </td>
                          <td>{record.projection_status}</td>
                          <td>{record.projected_by ?? "—"}</td>
                          <td>
                            {record.projected_at
                              ? new Date(record.projected_at).toLocaleString()
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          )}

          {audit.length > 0 && (
            <section className="results-card">
              <div className="results-card-header">
                <h2>Audit trail (this session, local only)</h2>
              </div>
              {audit.map((entry, index) => (
                <div className="re-muted" key={index}>{entry}</div>
              ))}
            </section>
          )}

        </main>

      </div>

    </div>
  );
}

/* ============================================================
   ATTERBERG
   ============================================================ */

interface AtterbergProps {
  method: string;
  /** Real active method profiles for this test type (lab.method_definition). */
  methodOptions: string[];
  preparation: string;
  sieveSize: string;
  passingSieve: string;
  naturalWaterContent: string;
  atterbergTab: AtterbergTab;

  setMethod: (value: string) => void;
  setPreparation: (value: string) => void;
  setSieveSize: (value: string) => void;
  setPassingSieve: (value: string) => void;
  setNaturalWaterContent: (value: string) => void;
  setAtterbergTab: (value: AtterbergTab) => void;

  liquidTrials: LiquidTrial[];
  plasticTrials: PlasticTrial[];

  updateLiquidTrial: (
    trial: number,
    field: keyof LiquidTrial,
    value: string | boolean
  ) => void;

  updatePlasticTrial: (
    trial: number,
    field: keyof PlasticTrial,
    value: string
  ) => void;

  addLiquidTrial: () => void;
  removeLiquidTrial: (trial: number) => void;
  addPlasticTrial: () => void;
  removePlasticTrial: (trial: number) => void;

  // Live calculation result, so the reported values and the flow curve
  // reflect the trials the user actually entered. Null before calculate.
  evaluation: Evaluation | null;
}

function AtterbergSection({
  method,
  methodOptions,
  preparation,
  sieveSize,
  passingSieve,
  naturalWaterContent,
  atterbergTab,
  setMethod,
  setPreparation,
  setSieveSize,
  setPassingSieve,
  setNaturalWaterContent,
  setAtterbergTab,
  liquidTrials,
  plasticTrials,
  updateLiquidTrial,
  updatePlasticTrial,
  addLiquidTrial,
  removeLiquidTrial,
  addPlasticTrial,
  removePlasticTrial,
  evaluation,
}: AtterbergProps) {

  return (
    <section className="results-card">

      <div className="results-card-header">

        <h2>
          Liquid and plastic limits
        </h2>

        <span className="ags-label">
          AGS&nbsp;&nbsp;LLPL
        </span>

      </div>

      <div className="method-grid">

        <Field label="Method profile">

          <select
            value={method}
            onChange={(event) =>
              setMethod(event.target.value)
            }
          >

            {/* Active method definitions for Atterberg from the database. */}
            {methodOptions.length === 0 && (
              <option value="">
                No active method for this test type
              </option>
            )}

            {methodOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}

          </select>

        </Field>

        <Field label="Preparation">

          <select
            value={preparation}
            onChange={(event) =>
              setPreparation(event.target.value)
            }
          >

            <option>
              Wet preparation
            </option>

            <option>
              Dry preparation
            </option>

          </select>

        </Field>

        <Field label="Sieve size (mm)">

          <input
            value={sieveSize}
            onChange={(event) =>
              setSieveSize(event.target.value)
            }
          />

        </Field>

        <Field label="Passing sieve (%)">

          <input
            value={passingSieve}
            onChange={(event) =>
              setPassingSieve(event.target.value)
            }
          />

        </Field>

        {/* Optional: when present the server engine additionally reports
            liquidity and consistency indices for this specimen. */}
        <Field label="Natural water content (%)">

          <input
            type="number"
            min="0"
            step="0.1"
            value={naturalWaterContent}
            onChange={(event) =>
              setNaturalWaterContent(event.target.value)
            }
            placeholder="optional"
          />

        </Field>

      </div>

      <div className="subtabs">

        <button
          type="button"
          className={
            atterbergTab === "liquid"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setAtterbergTab("liquid")
          }
        >
          Liquid limit trials
        </button>

        <button
          type="button"
          className={
            atterbergTab === "plastic"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setAtterbergTab("plastic")
          }
        >
          Plastic limit trials
        </button>

        <button
          type="button"
          className={
            atterbergTab === "flow"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setAtterbergTab("flow")
          }
        >
          Flow curve
        </button>

        <button
          type="button"
          className={
            atterbergTab === "shrinkage"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setAtterbergTab("shrinkage")
          }
        >
          Shrinkage
        </button>

      </div>

      {atterbergTab === "liquid" && (

        <LiquidLimitTable
          trials={liquidTrials}
          updateTrial={updateLiquidTrial}
          addTrial={addLiquidTrial}
          removeTrial={removeLiquidTrial}
        />

      )}

      {atterbergTab === "plastic" && (

        <PlasticLimitTable
          trials={plasticTrials}
          updateTrial={updatePlasticTrial}
          addTrial={addPlasticTrial}
          removeTrial={removePlasticTrial}
        />

      )}

      {atterbergTab === "flow" && (
        <AtterbergFlowCurve evaluation={evaluation} />
      )}

      {atterbergTab === "shrinkage" && (
        <div className="simple-method-panel">

          <h3>
            Shrinkage
          </h3>

          <p className="re-note">
            Shrinkage-limit readings are not part of an Atterberg test: nothing
            typed into this subtab was ever calculated or saved. Register a
            Shrinkage Limit (LSLT) test to enter and calculate them.
          </p>

        </div>
      )}

      {(atterbergTab === "liquid" ||
        atterbergTab === "plastic" ||
        atterbergTab === "flow") && (

        <div className="atterberg-bottom">

          <AtterbergFlowCurve evaluation={evaluation} />

          <ReportedValues evaluation={evaluation} />

        </div>

      )}

    </section>
  );
}

/* ============================================================
   LIQUID LIMIT
   ============================================================ */

/** Live water content from the three weighed masses (same formula as the
 *  calculation engine), or an em-dash while a value is missing/invalid. */
function waterContentOf(
  containerMass: string,
  wetContainer: string,
  dryContainer: string
): string {
  if (
    containerMass.trim() === "" ||
    wetContainer.trim() === "" ||
    dryContainer.trim() === ""
  ) {
    return "—";
  }

  const c = Number(containerMass);
  const w = Number(wetContainer);
  const d = Number(dryContainer);

  if (!(d > c) || !(w >= d)) return "—";

  return (((w - d) / (d - c)) * 100).toFixed(1);
}

function LiquidLimitTable({
  trials,
  updateTrial,
  addTrial,
  removeTrial,
}: {
  trials: LiquidTrial[];

  updateTrial: (
    trial: number,
    field: keyof LiquidTrial,
    value: string | boolean
  ) => void;

  addTrial: () => void;
  removeTrial: (trial: number) => void;
}) {

  return (
    <div className="table-scroll">

      <table className="results-table">

        <thead>

          <tr>
            <th>Trial</th>
            <th>Blows</th>
            <th>Container</th>
            <th>Container (g)</th>
            <th>Wet + container (g)</th>
            <th>Dry + container (g)</th>
            <th>Water content (%)</th>
            <th>Use</th>
            <th />
          </tr>

        </thead>

        <tbody>

          {trials.length === 0 && (
            <tr>
              <td colSpan={9} className="re-muted">
                No liquid-limit trials yet. Add at least three trials for a
                flow curve.
              </td>
            </tr>
          )}

          {trials.map((trial) => (

            <tr key={trial.trial}>

              <td>
                {trial.trial}
              </td>

              <td>

                <input
                  value={trial.blows}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "blows",
                      event.target.value
                    )
                  }
                />

              </td>

              <td className="container-cell">

                <input
                  value={trial.container}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "container",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.containerMass}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "containerMass",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.wetContainer}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "wetContainer",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.dryContainer}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "dryContainer",
                      event.target.value
                    )
                  }
                />

              </td>

              <td className="calculated-cell">
                {waterContentOf(
                  trial.containerMass,
                  trial.wetContainer,
                  trial.dryContainer
                )}
              </td>

              <td>

                <button
                  type="button"
                  className={
                    trial.use
                      ? "use-button active"
                      : "use-button"
                  }
                  onClick={() =>
                    updateTrial(
                      trial.trial,
                      "use",
                      !trial.use
                    )
                  }
                >
                  {trial.use ? "Yes" : "No"}
                </button>

              </td>

              <td>

                <button
                  type="button"
                  className="use-button"
                  title="Remove trial"
                  onClick={() => removeTrial(trial.trial)}
                >
                  ×
                </button>

              </td>

            </tr>

          ))}

        </tbody>

      </table>

      <button type="button" className="re-add" onClick={addTrial}>
        + Add liquid trial
      </button>

    </div>
  );
}

/* ============================================================
   PLASTIC LIMIT
   ============================================================ */

function PlasticLimitTable({
  trials,
  updateTrial,
  addTrial,
  removeTrial,
}: {
  trials: PlasticTrial[];

  updateTrial: (
    trial: number,
    field: keyof PlasticTrial,
    value: string
  ) => void;

  addTrial: () => void;
  removeTrial: (trial: number) => void;
}) {

  return (
    <div className="table-scroll">

      <table className="results-table">

        <thead>

          <tr>
            <th>Trial</th>
            <th>Container</th>
            <th>Container (g)</th>
            <th>Wet + container (g)</th>
            <th>Dry + container (g)</th>
            <th>Water content (%)</th>
            <th />
          </tr>

        </thead>

        <tbody>

          {trials.length === 0 && (
            <tr>
              <td colSpan={7} className="re-muted">
                No plastic-limit trials yet. Add at least one trial.
              </td>
            </tr>
          )}

          {trials.map((trial) => (

            <tr key={trial.trial}>

              <td>
                {trial.trial}
              </td>

              <td className="container-cell">

                <input
                  value={trial.container}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "container",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.containerMass}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "containerMass",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.wetContainer}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "wetContainer",
                      event.target.value
                    )
                  }
                />

              </td>

              <td>

                <input
                  value={trial.dryContainer}
                  onChange={(event) =>
                    updateTrial(
                      trial.trial,
                      "dryContainer",
                      event.target.value
                    )
                  }
                />

              </td>

              <td className="calculated-cell">
                {waterContentOf(
                  trial.containerMass,
                  trial.wetContainer,
                  trial.dryContainer
                )}
              </td>

              <td>

                <button
                  type="button"
                  className="use-button"
                  title="Remove trial"
                  onClick={() => removeTrial(trial.trial)}
                >
                  ×
                </button>

              </td>

            </tr>

          ))}

        </tbody>

      </table>

      <button type="button" className="re-add" onClick={addTrial}>
        + Add plastic trial
      </button>

    </div>
  );
}

/* ============================================================
   FLOW CURVE
   ============================================================ */

function AtterbergFlowCurve({
  evaluation,
}: {
  evaluation: Evaluation | null;
}) {

  // Map the computed flow-curve points (x = blows, y = water content) into
  // the SVG chart area: x 70..560 (log blows), y 220..40 (inverted).
  const X0 = 70, X1 = 560, Y0 = 40, Y1 = 240;
  const BLOW_MIN = 1, BLOW_MAX = 100;

  const curve = evaluation?.curve ?? [];

  const wc = curve.map((p) => p.y).filter(Number.isFinite);
  const wMin = wc.length ? Math.min(...wc) : 20;
  const wMax = wc.length ? Math.max(...wc) : 80;
  const wSpan = wMax - wMin || 1;

  const sx = (blows: number) =>
    X0 + (Math.log10(Math.max(blows, BLOW_MIN)) - Math.log10(BLOW_MIN)) /
      (Math.log10(BLOW_MAX) - Math.log10(BLOW_MIN)) * (X1 - X0);
  const sy = (w: number) => Y1 - ((w - wMin) / wSpan) * (Y1 - Y0);

  // The last two curve rows are the fitted line endpoints (the engine appends
  // them after the trial rows), so draw the line through them and the trials
  // as points.
  const trialPts = curve.slice(0, Math.max(0, curve.length - 2));
  const fitPts = curve.slice(Math.max(0, curve.length - 2));

  return (
    <div className="flow-curve-card">

      <h3>
        Flow curve
      </h3>

      <div className="flow-chart">

        <div className="chart-y-label">
          Water content %
        </div>

        <svg
          viewBox="0 0 600 300"
          className="flow-svg"
          role="img"
          aria-label="Atterberg flow curve"
        >

          <line
            x1="70"
            y1="40"
            x2="70"
            y2="260"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="260"
            x2="560"
            y2="260"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="95"
            x2="560"
            y2="95"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="150"
            x2="560"
            y2="150"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="205"
            x2="560"
            y2="205"
            className="chart-grid"
          />

          <line
            x1="180"
            y1="40"
            x2="180"
            y2="260"
            className="chart-grid"
          />

          <line
            x1="300"
            y1="40"
            x2="300"
            y2="260"
            className="chart-grid"
          />

          <line
            x1="420"
            y1="40"
            x2="420"
            y2="260"
            className="chart-grid"
          />

          {fitPts.length === 2 && (
            <line
              x1={sx(fitPts[0].x)}
              y1={sy(fitPts[0].y)}
              x2={sx(fitPts[1].x)}
              y2={sy(fitPts[1].y)}
              className="flow-line"
            />
          )}

          {trialPts.map((p, i) => (
            <circle
              key={i}
              cx={sx(p.x)}
              cy={sy(p.y)}
              r="6"
              className="flow-point"
            />
          ))}

          <line
            x1={sx(25)}
            y1="40"
            x2={sx(25)}
            y2="260"
            className="blow-line"
          />

          <text
            x={sx(25) + 10}
            y="55"
            className="chart-label"
          >
            25 blows
          </text>

        </svg>

        <div className="chart-x-label">
          Blows (log scale)
        </div>

      </div>

    </div>
  );
}

/* ============================================================
   REPORTED VALUES
   ============================================================ */

function ReportedValues({
  evaluation,
}: {
  evaluation: Evaluation | null;
}) {

  // The engine emits results labelled "Liquid limit", "Plastic limit",
  // "Plasticity index", "Flow index" and "Classification aid". Before the
  // user calculates, evaluation is null so the card shows a clear hint
  // instead of fabricated values.
  const byLabel = new Map(
    (evaluation?.results ?? []).map((r) => [r.label, r])
  );

  const rows: { label: string; value: string }[] = [
    { label: "Liquid limit", value: byLabel.get("Liquid limit")?.value ?? "—" },
    { label: "Plastic limit", value: byLabel.get("Plastic limit")?.value ?? "—" },
    { label: "Plasticity index", value: byLabel.get("Plasticity index")?.value ?? "—" },
    { label: "Flow index", value: byLabel.get("Flow index")?.value ?? "—" },
  ];

  const classification = byLabel.get("Classification aid (interpretation only)");
  if (classification) {
    rows.push({ label: "Classification aid", value: classification.value });
  }

  return (
    <div className="reported-card">

      <h3>
        Reported values
      </h3>

      {evaluation === null ? (
        <div className="re-note">
          Enter the liquid and plastic limit trials, then press
          "Calculate and validate" to see the reported values here.
        </div>
      ) : (
        rows.map((r) => (
          <ReportedRow key={r.label} label={r.label} value={r.value} />
        ))
      )}

      <div className="classification-note">
        Classification is an interpretation aid.
        It must not overwrite the factual LL, PL or
        PI results.
      </div>

    </div>
  );
}

function ReportedRow({
  label,
  value,
}: {
  label: string;
  value: string;
}) {

  return (
    <div className="reported-row">

      <span>
        {label}
      </span>

      <strong>
        {value}
      </strong>

    </div>
  );
}

/* ============================================================
   CONSOLIDATION
   ============================================================ */

interface ConsolidationProps {
  method: string;
  /** Real active method profiles for this test type (lab.method_definition). */
  methodOptions: string[];
  setMethod: (value: string) => void;
  consolidationTab: ConsolidationTab;
  setConsolidationTab: (
    value: ConsolidationTab
  ) => void;
}

function ConsolidationSection({
  method,
  methodOptions,
  setMethod,
  consolidationTab,
  setConsolidationTab,
}: ConsolidationProps) {

  return (
    <section className="results-card">

      <div className="results-card-header">

        <h2>
          One-dimensional consolidation
        </h2>

        <span className="ags-label">
          AGS&nbsp;&nbsp;CONG + CONS
        </span>

      </div>

      <div className="consolidation-input-grid">

        <Field label="Method profile">

          <select
            value={method}
            onChange={(event) =>
              setMethod(event.target.value)
            }
          >

            {/* Active method definitions for consolidation from the database. */}
            {methodOptions.length === 0 && (
              <option value="">
                No active method for this test type
              </option>
            )}

            {methodOptions.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}

          </select>
        </Field>

        {/* Consolidation readings are display-only in this build: no engine,
            no save path, no persistence. Disabling the inputs makes the
            state truthful instead of collecting readings that vanish. */}
        <fieldset disabled style={{ border: "none", margin: 0, padding: 0, display: "contents" }}>
          <Field label="Diameter (mm)">
            <input />
          </Field>

          <Field label="Initial height (mm)">
            <input />
          </Field>

          <Field label="Initial void ratio">
            <input />
          </Field>

          <Field label="Initial water content (%)">
            <input />
          </Field>

          <Field label="Initial bulk density (Mg/m³)">
            <input />
          </Field>

          <Field label="Particle density (Mg/m³)">
            <input />
          </Field>

          <Field label="Temperature (C)">
            <input />
          </Field>
        </fieldset>

        <p className="re-note" style={{ gridColumn: "1 / -1", marginTop: 8 }}>
          Consolidation readings are display-only in this build: nothing typed
          here is calculated or saved. Binding to the consolidation tables is
          the next step for this module.
        </p>

      </div>

      <div className="subtabs consolidation-tabs">

        <button
          type="button"
          className={
            consolidationTab === "load"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setConsolidationTab("load")
          }
        >
          Load stages
        </button>

        <button
          type="button"
          className={
            consolidationTab === "time"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setConsolidationTab("time")
          }
        >
          Time readings
        </button>

        <button
          type="button"
          className={
            consolidationTab === "elog"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setConsolidationTab("elog")
          }
        >
          e-log stress
        </button>

        <button
          type="button"
          className={
            consolidationTab === "cv"
              ? "subtab active"
              : "subtab"
          }
          onClick={() =>
            setConsolidationTab("cv")
          }
        >
          Cv plots
        </button>

      </div>

      {consolidationTab === "load" && (
        <ConsolidationLoadStages />
      )}

      {consolidationTab === "time" && (
        <ConsolidationTimeReadings />
      )}

      {consolidationTab === "elog" && (
        <ElogStress />
      )}

      {consolidationTab === "cv" && (
        <CvPlots />
      )}

    </section>
  );
}

/* ============================================================
   CONSOLIDATION LOAD STAGES
   ============================================================ */

function ConsolidationLoadStages() {

  return (
    <div className="table-scroll">

      <table className="results-table consolidation-table">

        <thead>

          <tr>
            <th>Stage</th>
            <th>Direction</th>
            <th>Stress end (kPa)</th>
            <th>e start</th>
            <th>e end</th>
            <th>mv (m²/MN)</th>
            <th>Cv root (m²/yr)</th>
            <th>Cv log (m²/yr)</th>
          </tr>

        </thead>

        <tbody>

          {CONSOLIDATION_STAGES.length === 0 && (
            <tr>
              <td colSpan={8} className="re-muted">
                No load stages entered. Consolidation is display-only in this
                build - readings are not yet bound to a calculation engine.
              </td>
            </tr>
          )}

          {CONSOLIDATION_STAGES.map(
            (stage) => (

              <tr key={stage.stage}>

                <td>
                  {stage.stage}
                </td>

                <td>
                  {stage.direction}
                </td>

                <td>

                  <input
                    defaultValue={stage.stress}
                  />

                </td>

                <td>
                  {stage.eStart}
                </td>

                <td>
                  {stage.eEnd}
                </td>

                <td>
                  {stage.mv}
                </td>

                <td>
                  {stage.cvRoot}
                </td>

                <td>
                  {stage.cvLog}
                </td>

              </tr>

            )
          )}

        </tbody>

      </table>

    </div>
  );
}

/* ============================================================
   CONSOLIDATION TIME READINGS
   ============================================================ */

function ConsolidationTimeReadings() {

  return (
    <div className="table-scroll">

      <table className="results-table">

        <thead>

          <tr>
            <th>Stage</th>
            <th>Elapsed time</th>
            <th>Dial reading</th>
            <th>Settlement</th>
            <th>Comment</th>
          </tr>

        </thead>

        <tbody>

          <tr>
            <td colSpan={5} className="re-muted">
              No time readings entered. Time-deformation series entry is not
              implemented in this build.
            </td>
          </tr>

        </tbody>

      </table>

    </div>
  );
}

/* ============================================================
   E-LOG STRESS
   ============================================================ */

function ElogStress() {

  return (
    <div className="graph-panel">

      <h3>
        e-log stress relationship
      </h3>

      <div className="elog-chart">

        <svg
          viewBox="0 0 700 350"
          className="flow-svg"
        >

          <line
            x1="70"
            y1="40"
            x2="70"
            y2="300"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="300"
            x2="650"
            y2="300"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="100"
            x2="650"
            y2="100"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="170"
            x2="650"
            y2="170"
            className="chart-grid"
          />

          <line
            x1="70"
            y1="235"
            x2="650"
            y2="235"
            className="chart-grid"
          />

          <text
            x="350"
            y="170"
            textAnchor="middle"
            className="chart-label"
          >
            No consolidation readings yet
          </text>

        </svg>

      </div>

      <div className="graph-summary">

        <div className="re-note">
          Consolidation derived parameters (Cc, Cr, preconsolidation stress)
          are not computed in this build yet. They appear once consolidation
          readings are bound to the calculation engine.
        </div>

      </div>

    </div>
  );
}

/* ============================================================
   CV PLOTS
   ============================================================ */

function CvPlots() {

  return (
    <div className="cv-panel">

      <h3>
        Coefficient of consolidation
      </h3>

      <div className="cv-grid">

        <div className="cv-card">

          <h4>
            Root-time method
          </h4>

          <div className="mini-chart">
            <div className="mini-line" />
          </div>

          <strong>
            Not computed
          </strong>

        </div>

        <div className="cv-card">

          <h4>
            Log-time method
          </h4>

          <div className="mini-chart">
            <div className="mini-line second" />
          </div>

          <strong>
            Not computed
          </strong>

        </div>

      </div>

    </div>
  );
}

/* ============================================================
   COMMON COMPONENTS
   ============================================================ */

function WorkflowItem({
  number,
  label,
  active = false,
  done = false,
  pending = false,
  caption,
  hint,
  onClick,
}: {
  number: string;
  label: string;
  active?: boolean;
  done?: boolean;
  /** Stage not reached yet: shown muted so it cannot be mistaken for progress. */
  pending?: boolean;
  caption?: string;
  hint?: string;
  onClick?: () => void;
}) {

  const className = active
    ? "workflow-item active"
    : done
    ? "workflow-item done"
    : pending
    ? "workflow-item pending"
    : "workflow-item";

  const inner = (
    <>
      <span className="workflow-head">
        <span className="workflow-number">
          {number}
        </span>

        <strong>
          {label}
        </strong>
      </span>

      {caption && (
        <span className="workflow-caption">
          {caption}
        </span>
      )}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={`${className} workflow-item-button`}
        title={hint}
        onClick={onClick}
      >
        {inner}
      </button>
    );
  }

  return (
    <div className={className} title={hint}>
      {inner}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {

  return (
    <label className="field">

      <span className="field-label">
        {label}
      </span>

      {children}

    </label>
  );
}