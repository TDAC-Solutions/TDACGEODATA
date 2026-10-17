import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./AuthContext";
import { LOGIN } from "../routes";

export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return <div>Loading...</div>;
  }

  if (!isAuthenticated) {
    return <Navigate to={LOGIN} replace />;
  }

  return <Outlet />;
}