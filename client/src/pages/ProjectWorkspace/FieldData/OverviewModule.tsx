import { useAuth } from "../../../auth/AuthContext";
import { BorelogReportPreview } from "./BorelogReportPreview";
import { FieldAuditPanel } from "./FieldAuditPanel";

interface OverviewModuleProps {
  projectId: string;
  locaId: string;
}

/**
 * Field Data → Overview.
 *
 * Two independent things, deliberately kept apart:
 *
 *   1. The borehole report — one continuous, depth-proportional log for the
 *      full depth, plus the Generate PDF button for the paginated version. It
 *      reads its own data, so it owns no loader here.
 *
 *   2. The audit panel — admin only.
 *
 * SoilProfileGraph.tsx is left on disk, unused: the depth-proportional log
 * supersedes it, and removing the file is a separate decision.
 */
export function OverviewModule({ projectId, locaId }: OverviewModuleProps) {
  return (
    <div>
      <BorelogReportPreview projectId={projectId} locaId={locaId} />

      <AdminAuditPanel projectId={projectId} locaId={locaId} />
    </div>
  );
}

/**
 * The audit panel, gated here rather than inside FieldAuditPanel.
 *
 * Two reasons for gating at the call site instead of within the panel:
 *
 *   * Visibility is decided by the module that decides what the tab shows. The
 *     panel has one job -- draw audit data -- and keeps no policy of its own,
 *     which is what made it reusable.
 *   * `user?.role === "admin"` evaluates to false while the session is still
 *     restoring, so the panel is never rendered for a user whose role has not
 *     loaded. Written out in full rather than folded into a helper so the check
 *     cannot be quietly weakened later: a non-admin must never see this panel,
 *     let alone drive it.
 *
 * This is the client half of the gate only. The real one is on the server --
 * every endpoint under /field-data/audit requires get_current_admin and answers
 * 403 for anyone else -- so hiding the panel here is presentation, not access
 * control.
 */
function AdminAuditPanel({
  projectId,
  locaId,
}: OverviewModuleProps) {
  const { user } = useAuth();

  if (user === null || user.role !== "admin") {
    return null;
  }

  return <FieldAuditPanel projectId={projectId} locaId={locaId} />;
}