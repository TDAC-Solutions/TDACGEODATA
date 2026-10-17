import { useEffect, useMemo, useState } from "react";
import {
  getProjectSamples,
  getProjectSampleTests,
  createProjectLabTestsBulk,
  ApiStatusError,
  type ProjectSample,
} from "../../../../api/fieldData";
import {
  getLabMethods,
  type LabMethod,
} from "../../../../api/labMethods";

interface TestRegisterTabProps {
  projectId: string;
}

/** One row from getProjectSampleTests. `test_id === null` means the sample
    exists but has no laboratory test yet ("NOT_TESTED"). */
interface SampleTestRow {
  sample_id: string;
  loca_id: string;
  test_id: string | null;
  test_type: string | null;
  spec_ref: string | null;
  current_revision: number | null;
  status: string;
}

/** The test types the lab module supports. Order matches the catalogue
    used in Results Entry so both tabs read identically. */
const TEST_TYPES = [
  { value: "PSD", label: "Particle Size Distribution" },
  { value: "PARTICLE_DENSITY", label: "Particle Density" },
  { value: "ATTERBERG", label: "Atterberg" },
  { value: "SHRINKAGE_LIMIT", label: "Shrinkage Limit" },
  { value: "TRIAXIAL_UU", label: "Triaxial UU" },
  { value: "CONSOLIDATION", label: "Consolidation" },
] as const;

export function TestRegisterTab({
  projectId,
}: TestRegisterTabProps) {
  const [samples, setSamples] = useState<ProjectSample[]>([]);
  const [selectedLocation, setSelectedLocation] = useState("ALL");
  const [selectedTestType, setSelectedTestType] = useState("ALL");
  const [selectedStatus, setSelectedStatus] = useState("ALL");
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [selectedSample, setSelectedSample] =
    useState<ProjectSample | null>(null);
  const [sampleTests, setSampleTests] = useState<SampleTestRow[]>([]);

  // Multi-select register state. Specimen Ref is shared across every test
  // in the batch; the method is chosen per test type because each type has
  // its own active method definitions.
  const [specimenRef, setSpecimenRef] = useState("SPEC-01");
  const [selectedTestTypes, setSelectedTestTypes] = useState<string[]>([]);
  const [methodByType, setMethodByType] = useState<Record<string, string>>(
    {}
  );

  const [methods, setMethods] = useState<LabMethod[]>([]);
  const [laboratory, setLaboratory] = useState("TDAC Laboratory");
  const [technician, setTechnician] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    getLabMethods()
      .then(setMethods)
      .catch(() => setMethods([]));
  }, []);

  useEffect(() => {
    async function loadSamples() {
      try {
        setLoading(true);
        setError("");

        const [samplesData, sampleTestsData] = await Promise.all([
          getProjectSamples(projectId),
          getProjectSampleTests(projectId),
        ]);

        setSamples(samplesData);
        setSampleTests(sampleTestsData);
      } catch (err) {
        console.error(err);
        setError("Failed to load project samples.");
      } finally {
        setLoading(false);
      }
    }

    loadSamples();
  }, [projectId]);

  function methodsForType(testType: string): LabMethod[] {
    return methods.filter((method) => method.test_type === testType);
  }

  /** Every test registered against a sample, not just the first. A sample
      can carry several after a multi-select registration, so a single row
      would hide all but one of them. */
  /** Group tests by "locaId|sampleId" once, instead of per sample. */
  const testsBySample = useMemo(() => {
    const index = new Map<string, SampleTestRow[]>();
    for (const test of sampleTests) {
      const key = `${test.loca_id}|${test.sample_id}`;
      const bucket = index.get(key);
      if (bucket) bucket.push(test);
      else index.set(key, [test]);
    }
    return index;
  }, [sampleTests]);

  function testsForSample(sample: ProjectSample): SampleTestRow[] {
    // Index lookup rather than a full scan. This ran over the entire tests
    // array once per sample, so the cost was samples x tests on every
    // filter change.
    return (
      testsBySample.get(`${sample.loca_id}|${sample.sample_id}`) ?? []
    ).filter((test) => test.test_id !== null);
  }

    /** Would the server's unique key refuse this test?

        The unique key on lab."test" is
        (file_fset, loca_id, samp_id, spec_ref, test_type, current_revision),
        so a collision needs the same type AND the same specimen reference on
        the same sample. A different specimen ref is always accepted, even for
        a type the sample already carries, because that is how a legitimate
        repeat test on a second specimen is registered. */
    function existingTestAt(
      sample: ProjectSample,
      type: string,
      ref: string,
      rows: SampleTestRow[] = sampleTests
    ): SampleTestRow | null {
      const trimmed = ref.trim();

      if (!trimmed) return null;

      return (
        rows.find(
          (test) =>
            test.sample_id === sample.sample_id &&
            test.loca_id === sample.loca_id &&
            test.test_id !== null &&
            test.test_type === type &&
            test.spec_ref === trimmed
        ) ?? null
      );
    }

  function toggleTestType(testType: string) {
    if (selectedTestTypes.includes(testType)) {
      setSelectedTestTypes(
        selectedTestTypes.filter((type) => type !== testType)
      );

      // Drop the method choice too. Leaving it behind is invisible state
      // that would resurrect a stale id if the type is re-ticked later.
      setMethodByType((current) => {
        const { [testType]: _dropped, ...rest } = current;
        return rest;
      });

      return;
    }

    setSelectedTestTypes([...selectedTestTypes, testType]);

    // Auto-pick the first active method so a fresh tick is never left in a
    // "checked but no method" state.
    const first = methodsForType(testType)[0];

    if (first) {
      setMethodByType((current) => ({
        ...current,
        [testType]: first.method_definition_id,
      }));
    }
  }

  function closeRegisterForm() {
    setSelectedSample(null);
    setSelectedTestTypes([]);
    setMethodByType({});
    setSaveError("");
    setSpecimenRef("SPEC-01");
  }

  async function handleCreateTests() {
    if (!selectedSample) return;

    if (!specimenRef.trim()) {
      setSaveError("Specimen Ref is required.");
      return;
    }

    if (selectedTestTypes.length === 0) {
      setSaveError("Select at least one test type.");
      return;
    }

    const missing = selectedTestTypes.filter((type) => !methodByType[type]);

    if (missing.length > 0) {
      setSaveError(
        `Select an active method for: ${missing.join(", ")}. ` +
          "A test type with no active method cannot be registered."
      );
      return;
    }

    // A collision is a real (type, specimen ref) clash on this sample.
    // Stop before the request so the batch never has to be rolled back
    // server-side. The button is already disabled in this case; this is the
    // net for a click that bypasses it.
    const clashes = selectedTestTypes.filter(
      (type) => existingTestAt(selectedSample, type, specimenRef) !== null
    );

    if (clashes.length > 0) {
      setSaveError(
        `${clashes.length} selected test${
          clashes.length === 1 ? "" : "s"
        } already exist at Specimen Ref ${specimenRef.trim()}. ` +
          "Change the Specimen Ref to register them on a new specimen."
      );
      return;
    }

    const tests = selectedTestTypes.map((type) => ({
      loca_id: selectedSample.loca_id,
      samp_id: selectedSample.sample_id,
      specimen_ref: specimenRef.trim(),
      test_type: type,
      method_definition_id: methodByType[type],
      laboratory,
      technician: technician || undefined,
    }));

    try {
      setSaving(true);
      setSaveError("");

      await createProjectLabTestsBulk(projectId, tests);

      closeRegisterForm();

      // Reload so the new tests appear in the register straight away.
      const refreshed = await getProjectSampleTests(projectId);
      setSampleTests(refreshed);
    } catch (err) {
      console.error(err);

      // A 409 from the unique-key upsert means another session created one of
      // these tests between our local snapshot load and this submit. The
      // local view is now stale: refetch immediately so the colliding row
      // appears greyed out, and tell the user exactly what changed.
      if (err instanceof ApiStatusError && err.status === 409) {
        try {
          const refreshed = await getProjectSampleTests(projectId);
          setSampleTests(refreshed);

          // Re-identify which types now collide so the message names them.
          // The refreshed rows are passed explicitly: `sampleTests` in this
          // closure is still the stale pre-refetch snapshot, so asking the
          // state directly would always report "the selected test types".
          const nowClashing = selectedTestTypes.filter(
            (type) =>
              existingTestAt(selectedSample, type, specimenRef, refreshed) !==
              null
          );
          const details = nowClashing.length
            ? nowClashing.join(", ")
            : "the selected test types";
          setSaveError(
            `${details} already exist at Specimen Ref ${specimenRef.trim()} ` +
              "(registered by another session) - the register has been " +
              "refreshed and the colliding row(s) are greyed out. Change " +
              "the Specimen Ref to register them on a new specimen."
          );
          return;
        } catch (reloadErr) {
          // The 409 already happened; a reload failure must not mask it.
          console.error("Register refresh failed after a 409:", reloadErr);
          setSaveError(
            "Another session registered one of these tests. Reload the page " +
              "to see the current register state."
          );
          return;
        }
      }

      setSaveError(
        err instanceof Error
          ? err.message
          : "Failed to create laboratory tests."
      );
    } finally {
      setSaving(false);
    }
  }

  const locations = Array.from(
    new Set(samples.map((sample) => sample.loca_id))
  ).sort();

  const filteredSamples = samples.filter((sample) => {
    const matchesLocation =
      selectedLocation === "ALL" ||
      sample.loca_id === selectedLocation;

    const sampleTestRows =
      testsBySample.get(`${sample.loca_id}|${sample.sample_id}`) ?? [];

    const hasTests = sampleTestRows.some((test) => test.test_id !== null);

    const matchesTestType =
      selectedTestType === "ALL" ||
      sampleTestRows.some((test) => test.test_type === selectedTestType) ||
      (selectedTestType === "NOT_TESTED" && !hasTests);

    const matchesStatus =
      selectedStatus === "ALL" ||
      sampleTestRows.some((test) => test.status === selectedStatus) ||
      (selectedStatus === "NOT_TESTED" && !hasTests);

    const normalizedSearch = searchTerm.trim().toLowerCase();

    const matchesSearch =
      normalizedSearch === "" ||
      sample.sample_id.toLowerCase().includes(normalizedSearch) ||
      sample.loca_id.toLowerCase().includes(normalizedSearch);

    return (
      matchesLocation &&
      matchesTestType &&
      matchesStatus &&
      matchesSearch
    );
  });

  const groupedSamples = filteredSamples.reduce<
    Record<string, ProjectSample[]>
  >((groups, sample) => {
    if (!groups[sample.loca_id]) {
      groups[sample.loca_id] = [];
    }

    groups[sample.loca_id].push(sample);

    return groups;
  }, {});

  if (loading) {
    return (
      <div className="card">
        <h3>Test Register</h3>

        <p className="page-sub">Loading project samples...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card">
        <h3>Test Register</h3>

        <p className="page-sub">{error}</p>
      </div>
    );
  }

  // ------------------------------------------------------------------
  // Register form: one sample, N test types
  // ------------------------------------------------------------------
  if (selectedSample) {
    const existingTests = testsForSample(selectedSample);

    // Which of the ticked types would actually collide at the current
    // specimen reference. Empty when the reference is new to this batch,
    // which is the common case when re-testing a sample.
    const collisions = selectedTestTypes.filter(
      (type) => existingTestAt(selectedSample, type, specimenRef) !== null
    );

    return (
      <div className="lab-test-register">
        <div className="lab-test-register-header">
          <div className="lab-test-register-title">
            <div className="lab-test-register-title-icon">
              ⚗
            </div>

            <div>
              <h3>Register Laboratory Tests</h3>

              <p>
                Tick one or more test types. Each ticked type becomes
                one laboratory test row against this sample.
              </p>
            </div>
          </div>

          <button
            type="button"
            className="lab-test-back-button"
            onClick={closeRegisterForm}
          >
            ← Back to Samples
          </button>
        </div>

        <div className="lab-selected-sample">
          <div className="lab-selected-sample-title">
            <div className="lab-selected-sample-title-icon">
              ▱
            </div>

            <h4>Selected Sample</h4>
          </div>

          <div className="lab-selected-sample-grid">
            <div className="lab-selected-sample-item">
              <div className="lab-selected-sample-label">
                Sample ID
              </div>

              <div className="lab-selected-sample-value">
                {selectedSample.sample_id}
              </div>
            </div>

            <div className="lab-selected-sample-item">
              <div className="lab-selected-sample-label">
                Location / Borehole
              </div>

              <div className="lab-selected-sample-value">
                {selectedSample.loca_id}
              </div>
            </div>

            <div className="lab-selected-sample-item">
              <div className="lab-selected-sample-label">
                Depth From
              </div>

              <div className="lab-selected-sample-value">
                {selectedSample.depth_from} m
              </div>
            </div>

            <div className="lab-selected-sample-item">
              <div className="lab-selected-sample-label">
                Depth To
              </div>

              <div className="lab-selected-sample-value">
                {selectedSample.depth_to ?? "—"} m
              </div>
            </div>
          </div>
        </div>

        {existingTests.length > 0 && (
          <div className="lab-test-details lab-existing-tests">
            <div className="lab-test-details-header">
              <div className="lab-test-details-icon">✓</div>

              <div>
                <h4>Tests already registered</h4>

                <p>
                  A test type can be registered again on a new specimen of
                  the same sample. Use a different Specimen Ref below to
                  do that. Re-using one of the refs listed here for the
                  same test type will be refused.
                </p>
              </div>
            </div>

            <div className="table-scroll">
              <table className="dtable">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Specimen Ref</th>
                    <th>Revision</th>
                    <th>Status</th>
                  </tr>
                </thead>

                <tbody>
                  {existingTests.map((test) => (
                    <tr key={test.test_id}>
                      <td data-label="Test Type">
                        <strong>{test.test_type ?? "—"}</strong>
                      </td>

                      <td data-label="Specimen Ref">{test.spec_ref ?? "—"}</td>

                      <td data-label="Revision">{test.current_revision ?? "—"}</td>

                      <td data-label="Status">{test.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div className="lab-test-details">
          <div className="lab-test-details-header">
            <div className="lab-test-details-icon">⚗</div>

            <div>
              <h4>Test Details</h4>

              <p>
                Specimen Ref, Laboratory and Technician are shared by
                every ticked test type in this batch.
              </p>
            </div>
          </div>

          <div className="lab-test-form-grid">
            <div className="lab-test-form-field">
              <label>
                Specimen Ref
                <span className="lab-test-required">*</span>
              </label>

              <input
                type="text"
                value={specimenRef}
                onChange={(event) =>
                  setSpecimenRef(event.target.value)
                }
                placeholder="Enter specimen reference"
              />

              <div className="lab-test-form-help">
                Shared across every ticked test type in this batch.
              </div>
            </div>

            <div className="lab-test-form-field">
              <label>
                Laboratory
                <span className="lab-test-required">*</span>
              </label>

              <input
                type="text"
                value={laboratory}
                onChange={(event) =>
                  setLaboratory(event.target.value)
                }
                placeholder="Enter laboratory name"
              />

              <div className="lab-test-form-help">
                Laboratory where the tests will be performed.
              </div>
            </div>

            <div className="lab-test-form-field">
              <label>Technician</label>

              <input
                type="text"
                value={technician}
                onChange={(event) =>
                  setTechnician(event.target.value)
                }
                placeholder="Enter technician name"
              />

              <div className="lab-test-form-help">
                Name of the laboratory technician (optional).
              </div>
            </div>
          </div>

          <div
            className="lab-test-form-field"
            style={{ marginTop: 18 }}
          >
            <label>
              Test Types
              <span className="lab-test-required">*</span>
            </label>

            <div className="lab-test-types">
              {TEST_TYPES.map(({ value, label }) => {
                const checked = selectedTestTypes.includes(value);
                const typeMethods = methodsForType(value);
                const hasMethods = typeMethods.length > 0;

                // Same (type, specimen ref) already on this sample - the
                // one case the server's unique key will refuse. Flagged
                // here so the user never pays for a round trip and a
                // server-side rollback.
                const collision = checked
                  ? existingTestAt(selectedSample, value, specimenRef)
                  : null;

                return (
                  <div
                    key={value}
                    className={`lab-test-type-row${
                      checked ? " checked" : ""
                    }${collision ? " collision" : ""}`}
                  >
                    <label className="lab-test-type-toggle">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleTestType(value)}
                      />

                      <span>{label}</span>
                    </label>

                    {checked && (
                      <select
                        value={methodByType[value] ?? ""}
                        onChange={(event) =>
                          setMethodByType((current) => ({
                            ...current,
                            [value]: event.target.value,
                          }))
                        }
                        disabled={!hasMethods}
                      >
                        {!hasMethods ? (
                          <option value="">
                            No active method for this test type
                          </option>
                        ) : (
                          typeMethods.map((method) => (
                            <option
                              key={method.method_definition_id}
                              value={method.method_definition_id}
                            >
                              {method.method_code} · {method.method_name}
                              {method.standard_reference
                                ? ` (${method.standard_reference})`
                                : ""}
                            </option>
                          ))
                        )}
                      </select>
                    )}

                    {collision && (
                      <div className="lab-test-type-collision">
                        Already registered at this Specimen Ref — revision{" "}
                        {collision.current_revision ?? 1} ·{" "}
                        {collision.status}. Change Specimen Ref to register
                        another {label.toLowerCase()} on a new specimen, or
                        untick.
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="lab-test-types-summary">
              {selectedTestTypes.length === 0
                ? "Tick one or more test types to register against this sample."
                : `${selectedTestTypes.length} test${
                    selectedTestTypes.length === 1 ? "" : "s"
                  } will be registered with the shared specimen ref.`}
            </div>
          </div>

          {saveError && (
            <div className="lab-test-form-error">{saveError}</div>
          )}

          {collisions.length > 0 && (
            <div className="lab-test-form-error">
              {collisions.length} selected test
              {collisions.length === 1 ? "" : "s"} already exist at
              Specimen Ref <b>{specimenRef.trim() || "—"}</b>. Change the
              Specimen Ref to register them on a new specimen.
            </div>
          )}

          {/* Disabled when a ticked type has no method, or when a ticked
              type collides with an existing (type, specimen ref). Neither
              was ever going to be valid, so the button says so rather than
              accepting the click and reporting it afterwards. */}
          <div className="lab-test-form-actions">
            <button
              type="button"
              className="lab-test-create-button"
              onClick={handleCreateTests}
              disabled={
                saving ||
                selectedTestTypes.length === 0 ||
                selectedTestTypes.some((type) => !methodByType[type]) ||
                collisions.length > 0
              }
            >
              +
              {saving
                ? "Saving..."
                : selectedTestTypes.length > 1
                ? ` Create ${selectedTestTypes.length} Tests`
                : " Create Test"}
            </button>

            <button
              type="button"
              className="lab-test-cancel-button"
              onClick={closeRegisterForm}
              disabled={saving}
            >
              × Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ------------------------------------------------------------------
  // Register list, grouped by location
  // ------------------------------------------------------------------
  return (
    <div className="card">
      <h3>Test Register</h3>

      <p className="page-sub">
        Select a sample to register one or more laboratory tests.
      </p>

      <div className="lab-register-filters">
        <label>
          <span>Location / Borehole</span>

          <select
            value={selectedLocation}
            onChange={(event) =>
              setSelectedLocation(event.target.value)
            }
          >
            <option value="ALL">All Locations</option>

            {locations.map((location) => (
              <option key={location} value={location}>
                {location}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Test Type</span>

          <select
            value={selectedTestType}
            onChange={(event) =>
              setSelectedTestType(event.target.value)
            }
          >
            <option value="ALL">All Test Types</option>
            <option value="NOT_TESTED">Not Tested</option>

            {TEST_TYPES.map((type) => (
              <option key={type.value} value={type.value}>
                {type.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span>Status</span>

          <select
            value={selectedStatus}
            onChange={(event) =>
              setSelectedStatus(event.target.value)
            }
          >
            <option value="ALL">All Statuses</option>
            <option value="NOT_TESTED">Not Tested</option>
            <option value="DRAFT">Draft</option>
            <option value="CALCULATED">In Progress</option>
            <option value="SUBMITTED">Submitted</option>
            <option value="CHECKED">For Check</option>
            <option value="APPROVED">Approved</option>
            <option value="PUBLISHED">Published</option>
          </select>
        </label>

        <label>
          <span>Search</span>

          <input
            type="text"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Sample ID or borehole..."
          />
        </label>
      </div>

      {filteredSamples.length === 0 ? (
        <div className="lab-sample-empty">
          <div className="lab-sample-empty-icon">⚗</div>

          <h4>No samples found</h4>

          <p>
            Try adjusting the location filter or select a different
            location.
          </p>
        </div>
      ) : (
        <div className="lab-sample-groups">
          {Object.entries(groupedSamples).map(
            ([location, locationSamples]) => (
              <div key={location} className="lab-sample-group">
                <div className="lab-sample-group-header">
                  <div>
                    <h4>{location}</h4>

                    <span>
                      {locationSamples.length} sample
                      {locationSamples.length === 1 ? "" : "s"}
                    </span>
                  </div>
                </div>

                <div className="table-scroll">
                  <table className="dtable">
                    <thead>
                      <tr>
                        <th>Tests</th>
                        <th>Location</th>
                        <th>Sample</th>
                        <th>Depth</th>
                        <th>Test Types</th>
                        <th>Status</th>
                        <th>Action</th>
                      </tr>
                    </thead>

                    <tbody>
                      {locationSamples.map((sample) => {
                        const activeTests = testsForSample(sample);
                        const count = activeTests.length;

                        return (
                          <tr
                            key={`${sample.loca_id}-${sample.sample_id}`}
                          >
                            <td data-label="Tests">
                              <strong>
                                {count === 0
                                  ? "—"
                                  : count === 1
                                  ? "1 test"
                                  : `${count} tests`}
                              </strong>
                            </td>

                            <td data-label="Location">{sample.loca_id}</td>

                            <td data-label="Sample">{sample.sample_id}</td>

                            <td data-label="Depth">
                              {sample.depth_from}–
                              {sample.depth_to ?? "—"} m
                            </td>

                            <td data-label="Test Types">
                              {count === 0
                                ? "—"
                                : Array.from(
                                    new Set(
                                      activeTests
                                        .map((test) => test.test_type)
                                        .filter(Boolean)
                                    )
                                  ).join(", ")}
                            </td>

                            <td data-label="Status">
                              {count === 0
                                ? "NOT_TESTED"
                                : Array.from(
                                    new Set(
                                      activeTests.map((test) => test.status)
                                    )
                                  ).join(", ")}
                            </td>

                            <td data-label="Action">
                              <button
                                type="button"
                                className="button-secondary"
                                onClick={() =>
                                  setSelectedSample(sample)
                                }
                              >
                                {count > 0 ? "Open" : "Register Tests"}
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
