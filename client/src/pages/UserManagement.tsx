import { useEffect, useState } from "react";
import {
  createUser,
  getUsers,
  updateUser,
  updateUserStatus,
  deleteUser,
  type UserRecord,
} from "../api/users";
import "./UserManagement.css";

export function UserManagementPage() {
  const [users, setUsers] = useState<UserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState("");

  const [editingUser, setEditingUser] =
    useState<UserRecord | null>(null);

  async function loadUsers() {
    try {
      setLoading(true);
      setError(null);

      const data = await getUsers();
      setUsers(data);
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Unable to load users."
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleCreateUser() {
    setError(null);

    if (!username.trim()) {
      setError("Username is required.");
      return;
    }

    if (!password) {
      setError("Password is required.");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    if (!roleId) {
      setError("Please select a role.");
      return;
    }

    try {
      setSaving(true);

      await createUser({
        username: username.trim(),
        password,
        role_id: Number(roleId),
      });

      setUsername("");
      setPassword("");
      setRoleId("");
      setShowForm(false);

      await loadUsers();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Unable to create user."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleStatusChange(
    userId: number,
    isActive: boolean
  ) {
    try {
      setError(null);

      await updateUserStatus(userId, isActive);

      await loadUsers();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Unable to update user status."
      );
    }
  }

  function openEditForm(user: UserRecord) {
    setEditingUser(user);
    setUsername(user.username);
    setPassword("");
    setRoleId(String(user.role_id));
    setShowForm(true);
    setError(null);
  }

  function closeForm() {
    setShowForm(false);
    setEditingUser(null);
    setUsername("");
    setPassword("");
    setRoleId("");
    setError(null);
  }

  async function handleUpdateUser() {
    if (!editingUser) {
      return;
    }

    setError(null);

    if (!username.trim()) {
      setError("Username is required.");
      return;
    }

    if (!roleId) {
      setError("Please select a role.");
      return;
    }

    if (password && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }

    try {
      setSaving(true);

      const updateData: {
        username?: string;
        password?: string;
        role_id?: number;
      } = {
        username: username.trim(),
        role_id: Number(roleId),
      };

      if (password) {
        updateData.password = password;
      }

      await updateUser(
        editingUser.id,
        updateData
      );

      closeForm();
      await loadUsers();
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Unable to update user."
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteUser(user: UserRecord) {
  const confirmed = window.confirm(
    `Are you sure you want to delete "${user.username}"?`
  );

  if (!confirmed) {
    return;
  }

  try {
    setError(null);

    await deleteUser(user.id);

    await loadUsers();
  } catch (error) {
    setError(
      error instanceof Error
        ? error.message
        : "Unable to delete user."
    );
  }
}

  return (
    <main className="page user-management">
      <div className="page-head">
        <div>
          <div className="eyebrow">
            ADMINISTRATION
          </div>

          <h1>User Management</h1>

          <p className="page-sub">
            Manage TDAC users, roles, and account status.
          </p>
        </div>

        {!showForm && (
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setEditingUser(null);
              setUsername("");
              setPassword("");
              setRoleId("");
              setError(null);
              setShowForm(true);
            }}
          >
            + Add User
          </button>
        )}
      </div>

      {showForm && (
        <div className="panel form-panel">
          <div className="panel-head">
            <h3 className="panel-title">
              {editingUser
                ? "Edit User"
                : "Add User"}
            </h3>
          </div>

          <div className="panel-body">
            <div className="viewgrid">
              <div>
                <div className="eyebrow">
                  USERNAME
                </div>

                <input
                  type="text"
                  value={username}
                  onChange={(e) =>
                    setUsername(e.target.value)
                  }
                  placeholder="Enter username"
                />
              </div>

              <div>
                <div className="eyebrow">
                  PASSWORD
                </div>

                <input
                  type="password"
                  value={password}
                  onChange={(e) =>
                    setPassword(e.target.value)
                  }
                  placeholder={
                    editingUser
                      ? "Leave blank to keep current password"
                      : "Minimum 8 characters"
                  }
                />
              </div>

              <div>
                <div className="eyebrow">
                  ROLE
                </div>

                <select
                  value={roleId}
                  onChange={(e) =>
                    setRoleId(e.target.value)
                  }
                >
                  <option value="">
                    Select role
                  </option>

                  <option value="2">
                    Engineer
                  </option>

                  <option value="10">
                    Client
                  </option>
                </select>
              </div>
            </div>

            {error && (
              <p className="page-sub">
                {error}
              </p>
            )}

            <div className="form-actions">
              <button
                type="button"
                className="btn btn-primary"
                onClick={
                  editingUser
                    ? handleUpdateUser
                    : handleCreateUser
                }
                disabled={saving}
              >
                {saving
                  ? editingUser
                    ? "Saving..."
                    : "Creating..."
                  : editingUser
                    ? "Save Changes"
                    : "Create User"}
              </button>

              <button
                type="button"
                className="btn"
                onClick={closeForm}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="panel users-panel">
        <div className="panel-head">
            <h3 className="panel-title">
            Users
            </h3>

            <span className="user-count">
            {users.length} {users.length === 1 ? "user" : "users"}
            </span>
        </div>

        <div className="panel-body">
          {loading && (
            <p className="page-sub">
              Loading users...
            </p>
          )}

          {!loading && error && !showForm && (
            <p className="page-sub">
              {error}
            </p>
          )}

          {!loading && !error && (
            <div style={{ overflowX: "auto" }}>
              <table className="users-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Actions</th>
                  </tr>
                </thead>

                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                        <td className="username-cell">
                            {user.username}
                        </td>

                      <td>
                        <span className="role-badge">
                            {user.role_name}
                        </span>
                      </td>

                      <td>
                        <span
                            className={`status-badge ${
                            user.is_active
                                ? "active"
                                : "inactive"
                            }`}
                        >
                            {user.is_active
                            ? "Active"
                            : "Inactive"}
                        </span>
                      </td>

                    <td className="created-cell">
                        {new Date(
                            user.created_at
                        ).toLocaleDateString()}
                    </td>

                      <td>
                        <div className="actions">
                            <button
                            type="button"
                            className="btn"
                            onClick={() =>
                                openEditForm(user)
                            }
                            >
                            Edit
                            </button>

                            <button
                            type="button"
                            className="btn"
                            onClick={() =>
                                handleStatusChange(
                                user.id,
                                !user.is_active
                                )
                            }
                            >
                            {user.is_active
                                ? "Deactivate"
                                : "Activate"}
                            </button>

                            <button
                            type="button"
                            className="btn delete-btn"
                            onClick={() =>
                                handleDeleteUser(user)
                            }
                            >
                            Delete
                            </button>
                        </div>
                        </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {!loading &&
            !error &&
            users.length === 0 && (
              <p className="page-sub">
                No users found.
              </p>
            )}
        </div>
      </div>
    </main>
  );
}