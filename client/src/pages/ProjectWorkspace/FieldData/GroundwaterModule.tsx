import { useEffect, useState } from "react";
import { getGroundwaterStatus } from "../../../api/fieldData";

interface GroundwaterModuleProps {
  projectId: string;
  locaId: string;
}

export function GroundwaterModule({
  projectId,
  locaId,
}: GroundwaterModuleProps) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reason, setReason] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        setLoading(true);
        setError(null);

        const status = await getGroundwaterStatus(projectId, locaId);

        if (!cancelled) {
          setReason(
            status.available
              ? null
              : status.reason ?? "Groundwater data is not available."
          );
        }
      } catch (err) {
        console.error("Failed to load groundwater status:", err);

        if (!cancelled) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load groundwater data."
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();

    return () => {
      cancelled = true;
    };
  }, [projectId, locaId]);

  if (loading) {
    return <p className="page-sub">Loading Field Data…</p>;
  }

  if (error) {
    return <p className="page-sub field-error">{error}</p>;
  }

  return (
    <div className="empty-state">
      <h3>Groundwater data unavailable</h3>
      <p>
        {reason ??
          "A confirmed database mapping for Groundwater has not been configured for this project."}
      </p>
    </div>
  );
}
