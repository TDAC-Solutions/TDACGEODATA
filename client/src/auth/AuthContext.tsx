import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import { getHome, login, logout } from "../api/auth";
import {
  AUTH_EXPIRED_EVENT,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setTokens,
} from "../api/token";

interface AuthUser {
  id: number;
  username: string;
  role: string;
}

interface AuthContextType {
  user: AuthUser | null;
  isAuthenticated: boolean;
  loading: boolean;
  loginUser: (username: string, password: string) => Promise<void>;
  logoutUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  const isAuthenticated = user !== null;

  useEffect(() => {
    async function restoreSession() {
      const accessToken = getAccessToken();
      const refreshToken = getRefreshToken();

      if (!accessToken || !refreshToken) {
        clearTokens();
        setLoading(false);
        return;
      }

      try {
        const data = await getHome();
        setUser(data.user);
      } catch {
        clearTokens();
        setUser(null);
      } finally {
        setLoading(false);
      }
    }

    restoreSession();
  }, []);

  // A refresh that cannot be renewed is broadcast by apiClient. Clearing the
  // user here lets ProtectedRoute redirect to /login instead of leaving an
  // authenticated-looking shell behind.
  useEffect(() => {
    function handleExpired() {
      setUser(null);
    }

    window.addEventListener(AUTH_EXPIRED_EVENT, handleExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleExpired);
  }, []);

  async function loginUser(username: string, password: string) {
    const data = await login(username, password);

    setTokens(data.access_token, data.refresh_token);

    try {
      const homeData = await getHome();
      setUser(homeData.user);
    } catch (error) {
      // Never leave valid tokens in storage with no user: the next render
      // would show the login page while the app believes it is signed in.
      clearTokens();
      setUser(null);
      throw error;
    }
  }

  async function logoutUser() {
    try {
      await logout();
    } catch (error) {
      console.error("Logout request failed:", error);
    } finally {
      clearTokens();
      setUser(null);
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated,
        loading,
        loginUser,
        logoutUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }

  return context;
}