import { useState } from "react";
import { OverviewTab } from "./tabs/OverviewTab";
import { SampleRegisterTab } from "./tabs/SampleRegisterTab";
import { TestRegisterTab } from "./tabs/TestRegisterTab";
import { ResultsEntryTab } from "./tabs/ResultsEntryTab";
import { HistoricDataTab } from "./tabs/HistoricDataTab";
import { QAApprovalTab } from "./tabs/QAApprovalTab";
import { AGSMappingTab } from "./tabs/AGSMappingTab";

type LabTab =
  | "overview"
  | "sample-register"
  | "test-register"
  | "results-entry"
  | "historic-data"
  | "qa-approval"
  | "ags-mapping";

/* Sample Register sits between Overview and Test Register because that is the
   order the work happens in: a sample is taken in the field, registered here,
   then tested -- Test Register and Results Entry both key off these Sample IDs. */
const TABS: { id: LabTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "sample-register", label: "Sample Register" },
  { id: "test-register", label: "Test Register" },
  { id: "results-entry", label: "Results Entry" },
  { id: "historic-data", label: "Historic Data" },
  { id: "qa-approval", label: "QA and Approval" },
  { id: "ags-mapping", label: "AGS Mapping" },
];
interface LabDataTabsProps {
  projectId: string;
}

export function LabDataTabs({
  projectId,
}: LabDataTabsProps) {
  const [activeTab, setActiveTab] = useState<LabTab>("overview");
  const [selectedTestId, setSelectedTestId] = useState<string | null>(null);

  return (
    <div>
      <div className="lab-data-tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            className={`lab-data-tab ${
              activeTab === tab.id ? "active" : ""
            }`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="lab-data-tab-content">
        {activeTab === "overview" && (
          <OverviewTab
            projectId={projectId}
            onAddTest={() => setActiveTab("test-register")}
            onOpenResults={(testId) => {
              setSelectedTestId(testId);
              setActiveTab("results-entry");
            }}
          />
        )}
        {activeTab === "sample-register" && (
          <SampleRegisterTab projectId={projectId} />
        )}
        {activeTab === "test-register" && (
          <TestRegisterTab projectId={projectId} />
        )}
        {activeTab === "results-entry" && (
          <ResultsEntryTab selectedTestId={selectedTestId} />
        )}
        {activeTab === "historic-data" && (
           <HistoricDataTab projectId={projectId} />
        )}
        {activeTab === "qa-approval" && (
           <QAApprovalTab projectId={projectId} />
        )}
        {activeTab === "ags-mapping" && <AGSMappingTab projectId={projectId} />}
      </div>
    </div>
  );
}
