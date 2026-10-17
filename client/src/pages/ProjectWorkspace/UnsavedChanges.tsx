import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
// NOT named unsavedChanges.ts: that differs from this file's own name only
// by case, which is a distinct file on Linux and the SAME file on Windows and
// macOS. Vite resolves an extensionless import by probing .ts before .tsx, so
// on a case-insensitive filesystem "./UnsavedChanges" silently resolved to the
// logic module -- which exports none of what is imported here -- and the
// SyntaxError took down the whole module graph before React could mount.
import {
  buildDiscardMessage,
  dirtyLabels as labelsOf,
  reportDirty,
  type DirtyRegistry,
} from "./unsavedChangesLogic";

/**
 * Field Data entry grids keep typed-but-unsubmitted rows in component state.
 * The workspace renders one tab at a time, so leaving the tab unmounts the
 * grid and the typing is gone with no warning and no undo. This provider
 * lets a grid announce that it holds unsaved rows, and gives the workspace
 * a single place to ask before throwing them away.
 *
 * Deliberately a context rather than props: the reporting grid is four
 * components below the thing that needs to ask, and drilling a callback
 * through the module, the tabs and the selector would put data-flow plumbing
 * in four files that have no other reason to know about it.
 */

type UnsavedChangesValue = {
  /** Report whether a surface currently holds unsaved rows. */
  report: (key: string, label: string, dirty: boolean) => void;
  /** Human-readable labels for everything currently dirty. */
  dirtyLabels: string[];
  /** Ask before discarding. Returns true when it is safe to navigate. */
  confirmDiscard: () => boolean;
};

const UnsavedChangesContext = createContext<UnsavedChangesValue | null>(
  null
);

export function UnsavedChangesProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [dirty, setDirty] = useState<DirtyRegistry>({});

  const report = useCallback(
    (key: string, label: string, isDirty: boolean) => {
      setDirty((current) => reportDirty(current, key, label, isDirty));
    },
    []
  );

  const labels = useMemo(() => labelsOf(dirty), [dirty]);
  const dirtyLabels = labels;

  const confirmDiscard = useCallback(() => {
    const message = buildDiscardMessage(labelsOf(dirty));
    if (message === null) return true;
    return window.confirm(message);
  }, [dirty]);

  // Covers the cases the in-app guard cannot: closing the tab, reloading,
  // or following a link out of the app entirely.
  useEffect(() => {
    if (dirtyLabels.length === 0) return;

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      // Legacy browsers need returnValue set; modern ones ignore the value.
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
    };
  }, [dirtyLabels.length]);

  const value = useMemo(
    () => ({ report, dirtyLabels, confirmDiscard }),
    [report, dirtyLabels, confirmDiscard]
  );

  return (
    <UnsavedChangesContext.Provider value={value}>
      {children}
    </UnsavedChangesContext.Provider>
  );
}

/**
 * Announce that this surface holds unsaved rows while `isDirty` is true.
 * Automatically withdraws on unmount, so a crashed or unmounted grid can
 * never leave a permanent phantom warning behind.
 */
export function useUnsavedChanges(
  key: string,
  label: string,
  isDirty: boolean
) {
  const context = useContext(UnsavedChangesContext);
  const report = context?.report;

  useEffect(() => {
    if (!report) return;
    report(key, label, isDirty);
    return () => report(key, label, false);
  }, [report, key, label, isDirty]);
}

/** For callers that are about to unmount whatever is holding unsaved rows. */
export function useUnsavedGuard(): () => boolean {
  const context = useContext(UnsavedChangesContext);
  return context?.confirmDiscard ?? (() => true);
}