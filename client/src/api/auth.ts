import { apiClient } from "./apiClient";

import { API_BASE_URL } from "../config";

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface CurrentUser {
  id: number;
  username: string;
  role: string;
}

export interface HomeResponse {
  message: string;
  user: CurrentUser;
}

/**
 * Log in with username and password.
 *
 * Tokens are returned to AuthContext, which is responsible
 * for storing them.
 */
export async function login(
  username: string,
  password: string
): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      username,
      password,
    }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to log in"
    );
  }

  return response.json();
}

/**
 * Get the currently authenticated user.
 *
 * apiClient automatically:
 * - adds the access token
 * - attempts token refresh on 401
 * - retries the request after refresh
 */
export async function getHome(): Promise<HomeResponse> {
  const response = await apiClient("/api/auth/home", {
    method: "GET",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to load user information"
    );
  }

  return response.json();
}

/**
 * Change the signed-in user's own password.
 *
 * The server revokes every session on success and returns a fresh token
 * pair; the caller stores it so this session survives.
 */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
  confirmPassword: string
): Promise<LoginResponse> {
  const response = await apiClient("/api/auth/change-password", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to change password"
    );
  }

  return response.json();
}

/**
 * Log out the current authenticated session.
 *
 * The actual token removal is handled by AuthContext/token.ts.
 */
export async function logout(): Promise<void> {
  const response = await apiClient("/api/auth/logout", {
    method: "POST",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to log out"
    );
  }
}