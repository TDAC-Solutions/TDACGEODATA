/**
 * Pure decision logic for the unsaved-changes guard.
 *
 * Kept apart from the React context so it can be exercised without a DOM.
 * The .mjs smoke tests in this repo run on plain node; jsdom is not a
 * dependency, so a test that needs one cannot run here.
 */

/** key -> label, present only while that surface holds unsaved rows. */
export type DirtyRegistry = Record<string, string>;

/**
 * Apply one surface's report to the registry.
 *
 * Returns the same object reference when nothing changed, so a component
 * reporting "still dirty" on every render does not loop.
 */
export function reportDirty(
  registry: DirtyRegistry,
  key: string,
  label: string,
  isDirty: boolean
): DirtyRegistry {
  if (isDirty) {
    if (registry[key] === label) return registry;
    return { ...registry, [key]: label };
  }
  if (!(key in registry)) return registry;
  const next = { ...registry };
  delete next[key];
  return next;
}

/** Human-readable labels for everything currently holding unsaved rows. */
export function dirtyLabels(registry: DirtyRegistry): string[] {
  return Object.values(registry);
}

/**
 * The prompt shown before discarding. Returns null when there is nothing to
 * discard, so callers can skip window.confirm entirely rather than showing
 * an empty warning.
 */
export function buildDiscardMessage(labels: string[]): string | null {
  if (labels.length === 0) return null;

  const subject = labels.length === 1 ? labels[0] : `${labels.length} grids`;
  const pronoun = labels.length === 1 ? "it" : "them";

  return (
    `You have unsaved entries in ${subject}. ` +
    `Leaving this screen will discard ${pronoun}.\n\n` +
    "Your typed rows have not been submitted to the database.\n\n" +
    "Continue anyway?"
  );
}