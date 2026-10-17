/* Register-row navigation — clicking a project row in the Portfolio register
   (Home.tsx, untouched) opens the Project Workspace for that project number.
   Delegated document-level click, same pattern as NewProjectModal.tsx.
   Rows only exist once the backend is connected; until then this stays silent. */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

export function RegisterRowNavigator() {
    const navigate = useNavigate();

    useEffect(() => {
        const onClick = (e : MouseEvent) => {
            const target = e.target as Element | null;
            if (!target?.closest) return;

            const row = target.closest("tr");
            if (!row) return;

            const table = row.closest(".register-table");
            if (!table) return;

            // The empty-register placeholder row is not a project
            if (row.classList.contains("empty-row")) return;

            const firstCell = row.querySelector("td");
            const projectId = firstCell?.textContent?.trim();
            if (!projectId) return;

            navigate(`/project/${encodeURIComponent(projectId)}`);
        };

        document.addEventListener("click", onClick);
        return () => document.removeEventListener("click", onClick);
    }, [navigate]);

    return null;
}
