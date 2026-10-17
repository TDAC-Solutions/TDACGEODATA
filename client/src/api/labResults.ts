/**
 * Dedicated Results Entry API layer (isolated from shared fieldData.ts).
 *
 * BACKEND STATUS: the server only exposes
 *   POST/GET /api/portfolio/projects/{id}/lab/tests   (test identity records)
 * There is NO endpoint for raw readings, calculated values, revisions,
 * submit-for-check or release, so this module deliberately exposes nothing
 * for them. A localStorage draft layer lived here and was removed: nothing
 * ever called it, and an unshipped silent cache is worse than an honest gap.
 */
import { getProjectSamples, type ProjectSample } from "./fieldData";

export { getProjectSamples };
export type { ProjectSample };

/** Server-side functions that do not exist yet. */
export const BACKEND_PENDING = [
  "Persist raw readings per test/revision",
  "Persist calculated values separately from raw readings",
  "Submit for check / status transitions",
  "Approved-revision lock + new-revision creation",
  "Audit trail read/write",
  "AGS projection storage",
  "Method-definition list (method_definition_id is required by POST lab/tests)",
] as const;
