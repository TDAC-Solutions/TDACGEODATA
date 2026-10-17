import {
  getAccessToken,
  refreshAccessToken,
  clearTokens,
  emitAuthExpired,
} from "./token";

import { API_BASE_URL } from "../config";

/**
 * Holds the currently running refresh operation.
 *
 * If multiple requests receive a 401 at the same time,
 * they will all wait for this same refresh operation
 * instead of starting separate refresh requests.
 */
let refreshPromise: Promise<string> | null = null;

export async function apiClient(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  let accessToken = getAccessToken();

  if (!accessToken) {
    throw new Error("Not authenticated");
  }

  const headers = new Headers(options.headers);

  // Respect a caller-supplied Authorization header instead of silently
  // replacing it with the session token.
  if (!headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  // FormData must set its own multipart boundary; a forced JSON content
  // type would corrupt file uploads.
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !headers.has("Content-Type")
  ) {
    headers.set("Content-Type", "application/json");
  }

  let response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  // Request succeeded or failed for a reason other than authentication.
  if (response.status !== 401) {
    return response;
  }

  /*
   * The access token has expired.
   *
   * If another request is already refreshing the token,
   * wait for that same refresh operation.
   */
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
      refreshPromise = null;
    });
  }

  try {
    accessToken = await refreshPromise;
  } catch (error) {
    // The session cannot be renewed. Clearing the tokens alone left the user
    // in an authenticated-looking shell whose every call failed; broadcast
    // the expiry so AuthProvider clears the user and ProtectedRoute sends
    // them to /login.
    clearTokens();
    emitAuthExpired();
    throw error;
  }

  /*
   * Retry the original request using the new access token.
   */
  const retryHeaders = new Headers(options.headers);

  // Same rule as the first attempt: a caller-supplied Authorization header
  // wins and is not stomped by the refreshed session token.
  if (!retryHeaders.has("Authorization")) {
    retryHeaders.set("Authorization", `Bearer ${accessToken}`);
  }

  // FormData must set its own multipart boundary; a forced JSON content
  // type would corrupt file uploads.
  if (
    options.body &&
    !(options.body instanceof FormData) &&
    !retryHeaders.has("Content-Type")
  ) {
    retryHeaders.set("Content-Type", "application/json");
  }

  response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: retryHeaders,
  });

  return response;
}