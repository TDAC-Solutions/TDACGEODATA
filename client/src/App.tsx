import { UserManagementPage } from "./pages/UserManagement";
import { AdminRoute } from "./auth/AdminRoute";
import { HashRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { PortfolioPage } from "./pages/Home";
import { LoginPage } from "./pages/Login";
import { ProjectWorkspacePage } from "./pages/ProjectWorkspace";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { ADMIN_USERS, HOME, LOGIN, PROJECT } from "./routes";
import { CreateProjectPage } from "./pages/CreateProject";
import { UnsavedChangesProvider } from "./pages/ProjectWorkspace/UnsavedChanges";

import "./shell.css";

/*
 * Routing note: this was converted to createHashRouter + useBlocker so that
 * leaving a project with unsaved entry-grid rows could be intercepted --
 * useBlocker only exists on data routers. It was reverted. Under the jsdom
 * harness React Router raised "A history only accepts one active listener"
 * and rendered nothing at all, so the migration could not be verified, and an
 * unverified rewrite of the app's entry point is a worse outcome than the
 * gap it was meant to close. Closing it properly needs either a working
 * data-router setup or a deliberate in-app guard on the portfolio links.
 */
export default function App() {
  return (
    /*
     * The provider sits ABOVE HashRouter deliberately. It uses no router
     * hooks, so that is legal, and it has to be up here: Topbar is a sibling
     * of the workspace, not a descendant, and the navigations that strand a
     * dirty grid (search, admin, logout) all originate there.
     */
    <UnsavedChangesProvider>
      <HashRouter>
        <Routes>

        {/* Public route */}
          <Route path={LOGIN} element={<LoginPage />} />

        {/* Protected application routes */}
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route index element={<PortfolioPage />} />
              <Route path="/projects/new" element={<CreateProjectPage />} />
              <Route path={PROJECT} element={<ProjectWorkspacePage />} />
              <Route element={<AdminRoute />}>
                <Route
                  path={ADMIN_USERS}
                  element={<UserManagementPage />}
                />
              </Route>
            </Route>
          </Route>

        {/* Catch-all */}
          <Route path="*" element={<Navigate to={HOME} replace />} />

          </Routes>
      </HashRouter>
    </UnsavedChangesProvider>
  );
}