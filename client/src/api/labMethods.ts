import { apiClient } from "./apiClient";

// ---------------------------------------------------------------------------
// Laboratory method definitions
//
// The active method list feeds the Test Register and Results Entry method
// dropdowns. method_definition_id is required by POST /lab/tests, so test
// creation is impossible until this list loads.
// ---------------------------------------------------------------------------

export interface LabMethod {
  method_definition_id: string;
  method_code: string;
  method_version: number;
  test_type: string;
  method_name: string;
  standard_body: string | null;
  standard_reference: string | null;
  standard_edition: string | null;
  calculation_package: string;
  calculation_package_version: string;
  ags_group: string[] | null;
  /** Released output keys the method declares (lab.method_definition.result_schema). */
  result_outputs: string[] | null;
}

export async function getLabMethods(): Promise<LabMethod[]> {
  const response = await apiClient("/api/portfolio/lab/methods");

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);
    throw new Error(
      errorBody?.detail ?? `Failed to load lab methods: ${response.status}`
    );
  }

  const result = await response.json();
  return result.methods;
}
