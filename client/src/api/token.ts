import { API_BASE_URL } from "../config";

const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, token);
}

export function setTokens(
  accessToken: string,
  refreshToken: string
): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/**
 * Broadcast that the session can no longer be renewed. AuthProvider listens
 * for this and clears the current user, which sends ProtectedRoute to /login.
 * Without it a failed refresh only cleared the tokens: the shell stayed on
 * screen looking authenticated while every request failed.
 */
export const AUTH_EXPIRED_EVENT = "tdac:auth-expired";

export function emitAuthExpired(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }
}

export async function refreshAccessToken(): Promise<string> {
  const refreshToken = getRefreshToken();

  if (!refreshToken) {
    throw new Error("No refresh token available");
  }

  // The token goes in a JSON body, not the query string: a query parameter
  // is written to access logs, proxy logs, and browser history, and this is
  // a long-lived credential.
  const response = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to refresh access token"
    );
  }

  const data = await response.json();

  setAccessToken(data.access_token);

  return data.access_token;
}