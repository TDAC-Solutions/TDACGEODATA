export interface WorkspaceTab {
  id: string;
  label: string;
}

export const WORKSPACE_TABS: WorkspaceTab[] = [
  { id: "overview", label: "Overview" },
  { id: "field", label: "Field Data" },
  { id: "lab", label: "Lab Data" },
  { id: "processed", label: "Processed Data" },
  { id: "interpretation", label: "Interpretation / Ground Model" },
  { id: "parameters", label: "Design Parameters" },
  { id: "design", label: "Design" },
  { id: "reports", label: "Reports" },
];

export function getTabLabel(tabId: string): string {
  const tab = WORKSPACE_TABS.find((item) => item.id === tabId);
  return tab?.label ?? "Workspace";
}
