import { apiClient } from "./apiClient";

export interface UserRecord {
  id: number;
  username: string;
  role_id: number;
  role_name: string;
  is_active: boolean;
  created_at: string;
}

export async function getUsers(): Promise<UserRecord[]> {
  const response = await apiClient("/api/auth/users", {
    method: "GET",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => null);

    throw new Error(
      data?.detail || "Unable to load users"
    );
  }

  const result = await response.json();

  return result.users;
}

export interface UserCreate {
  username: string;
  password: string;
  role_id: number;
}

export async function createUser(
  data: UserCreate
): Promise<UserRecord> {
  const response = await apiClient(
    "/api/auth/users",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        `Failed to create user: ${response.status}`
    );
  }

  const result = await response.json();

  return result.user;
}

export async function updateUserStatus(
  userId: number,
  isActive: boolean
): Promise<UserRecord> {
  const response = await apiClient(
    `/api/auth/users/${userId}/status?is_active=${isActive}`,
    {
      method: "PATCH",
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        `Failed to update user status: ${response.status}`
    );
  }

  const result = await response.json();

  return result.user;
}

export interface UserUpdate {
  username?: string;
  password?: string;
  role_id?: number;
}

export async function updateUser(
  userId: number,
  data: UserUpdate
): Promise<UserRecord> {
  const response = await apiClient(
    `/api/auth/users/${userId}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(data),
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        `Failed to update user: ${response.status}`
    );
  }

  const result = await response.json();

  return result.user;
}

export async function deleteUser(
  userId: number
): Promise<void> {
  const response = await apiClient(
    `/api/auth/users/${userId}`,
    {
      method: "DELETE",
    }
  );

  if (!response.ok) {
    const errorBody = await response.json().catch(() => null);

    throw new Error(
      errorBody?.detail ||
        `Failed to delete user: ${response.status}`
    );
  }
}