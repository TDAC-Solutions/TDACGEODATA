import { LabDataTabs } from "./LabDataTabs";

interface LabDataProps {
  projectId: string;
}

export function LabData({
  projectId,
}: LabDataProps) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2 className="panel-title">Lab Data</h2>
      </div>

      <div className="panel-body">
        <LabDataTabs projectId={projectId} />
      </div>
    </section>
  );
}