import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { HOME, LOGIN } from "../routes";

export function AdminRoute() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return <Navigate to={LOGIN} replace />;
  }

  if (user.role !== "admin") {
    return <Navigate to={HOME} replace />;
  }

  return <Outlet />;
}