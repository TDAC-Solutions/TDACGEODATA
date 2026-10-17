import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

import { RegisterRowNavigator } from "./RegisterRowNavigator";

export function AppShell() {
  return (
    <div className="shell">
      <RegisterRowNavigator />
      <Sidebar />
      <div className="shell-main">
        <Topbar />
        <main className="shell-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
