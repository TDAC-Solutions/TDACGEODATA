"""PUT /users/{id}, PATCH /users/{id}/status, DELETE /users/{id}.

All flows authenticate as admin id=1 and act on a target user; the id->row
map keeps the admin's own auth lookup separate from the target lookup.
"""
from tests.conftest import (
    ROLE_ENGINEER,
    auth_header,
    make_engineer_row,
    make_user_row,
    route_users_by_id,
    route_users_by_username,
)

ADMIN = {1: make_user_row()}


def with_target(target_id, target_row):
    mapping = dict(ADMIN)
    mapping[target_id] = target_row
    return mapping


def route_update(pool, row):
    pool.route("username = COALESCE($2, username)", row)


def route_status_update(pool, row):
    pool.route("is_active = $2", row)


def route_delete(pool, row):
    pool.route("DELETE FROM tdac.users", row)


class TestUpdateUser:
    def test_update_username(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_users_by_username(pool, {"renamed": None})
        route_update(pool, make_engineer_row(id=5, username="renamed"))
        resp = client.put(
            "/api/auth/users/5",
            json={"username": "renamed"},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200, resp.text
        args = pool.last_args("fetchrow", "UPDATE tdac.users")
        assert args[0] == 5 and args[1] == "renamed"

    def test_update_password_hashes_it(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_update(pool, make_engineer_row(id=5))
        resp = client.put(
            "/api/auth/users/5",
            json={"password": "brandnewpass1"},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200, resp.text
        args = pool.last_args("fetchrow", "UPDATE tdac.users")
        assert args[2].startswith("$2") and args[2] != "brandnewpass1"

    def test_update_role_id(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_update(pool, make_engineer_row(id=5, role_id=10, role_name="client"))
        resp = client.put("/api/auth/users/5", json={"role_id": 10}, headers=auth_header(1, 0))
        assert resp.status_code == 200, resp.text
        args = pool.last_args("fetchrow", "UPDATE tdac.users")
        assert args[3] == 10

    def test_combined_update(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_users_by_username(pool, {"combo": None})
        route_update(pool, make_engineer_row(id=5, username="combo"))
        resp = client.put(
            "/api/auth/users/5",
            json={"username": "combo", "password": "brandnewpass1", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200, resp.text

    def test_missing_user_404(self, client, pool):
        route_users_by_id(pool, with_target(999, None))
        resp = client.put(
            "/api/auth/users/999",
            json={"username": "whatever"},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 404

    def test_empty_payload_400(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        resp = client.put("/api/auth/users/5", json={}, headers=auth_header(1, 0))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "No changes provided"

    def test_username_taken_by_other_user_409(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_users_by_username(pool, {"clash": make_user_row(id=8, username="clash")})
        resp = client.put(
            "/api/auth/users/5",
            json={"username": "clash"},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 409

    def test_username_taken_by_self_is_allowed(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5, username="selfname")))
        route_users_by_username(pool, {"selfname": make_engineer_row(id=5, username="selfname")})
        route_update(pool, make_engineer_row(id=5, username="selfname"))
        resp = client.put(
            "/api/auth/users/5",
            json={"username": "selfname"},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200, resp.text

    def test_short_username_422(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        resp = client.put("/api/auth/users/5", json={"username": "x"}, headers=auth_header(1, 0))
        assert resp.status_code == 422

    def test_short_password_422(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        resp = client.put("/api/auth/users/5", json={"password": "abc"}, headers=auth_header(1, 0))
        assert resp.status_code == 422

    def test_non_admin_forbidden(self, client, pool):
        route_users_by_id(pool, {5: make_engineer_row()})
        assert client.put(
            "/api/auth/users/5", json={"username": "renamed"}, headers=auth_header(5, 0)
        ).status_code == 403


class TestChangeStatus:
    def test_deactivate_user(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_status_update(pool, make_engineer_row(id=5, is_active=False))
        resp = client.patch("/api/auth/users/5/status?is_active=false", headers=auth_header(1, 0))
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"] == "User deactivated successfully"

    def test_activate_user(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5, is_active=False)))
        route_status_update(pool, make_engineer_row(id=5, is_active=True))
        resp = client.patch("/api/auth/users/5/status?is_active=true", headers=auth_header(1, 0))
        assert resp.status_code == 200, resp.text
        assert resp.json()["message"] == "User activated successfully"

    def test_deactivation_bumps_token_gen_invalidating_sessions(self, client, pool):
        """Deactivating a user must revoke the sessions that exist now."""
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_status_update(pool, make_engineer_row(id=5, is_active=False))
        client.patch("/api/auth/users/5/status?is_active=false", headers=auth_header(1, 0))
        sql = pool.calls_with("fetchrow", "token_gen")
        assert sql, "deactivation must invalidate outstanding tokens"
        assert any(
            "FALSE" in c[1] and "token_gen" in c[1] for c in sql
        ), f"deactivation must bump token_gen, got: {[c[1] for c in sql]}"

    def test_reactivation_does_not_bump_token_gen(self, client, pool):
        """Reactivation has no session to revoke, so it must not invalidate
        tokens minted after the flag went back."""
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_status_update(pool, make_engineer_row(id=5, is_active=True))
        client.patch("/api/auth/users/5/status?is_active=true", headers=auth_header(1, 0))
        sql = pool.calls_with("fetchrow", "token_gen")
        assert sql, "the status update should still touch token_gen"
        assert any(
            "CASE WHEN $2 = FALSE" in c[1] for c in sql
        ), f"the bump must be conditional on deactivation: {[c[1] for c in sql]}"

    def test_cannot_change_own_status(self, client, pool):
        route_users_by_id(pool, {1: make_user_row(id=1)})
        resp = client.patch("/api/auth/users/1/status?is_active=false", headers=auth_header(1, 0))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "You cannot change your own account status"

    def test_missing_user_404(self, client, pool):
        route_users_by_id(pool, with_target(999, None))
        assert client.patch(
            "/api/auth/users/999/status?is_active=true", headers=auth_header(1, 0)
        ).status_code == 404

    def test_missing_query_param_422(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        assert client.patch("/api/auth/users/5/status", headers=auth_header(1, 0)).status_code == 422

    def test_non_admin_forbidden(self, client, pool):
        route_users_by_id(pool, {5: make_engineer_row()})
        assert client.patch(
            "/api/auth/users/5/status?is_active=false", headers=auth_header(5, 0)
        ).status_code == 403


class TestDeleteUser:
    def test_delete_user(self, client, pool):
        route_users_by_id(pool, with_target(5, make_engineer_row(id=5)))
        route_delete(pool, {"id": 5, "username": "enguser"})
        resp = client.delete("/api/auth/users/5", headers=auth_header(1, 0))
        assert resp.status_code == 200, resp.text
        assert resp.json()["user"] == {"id": 5, "username": "enguser"}
        args = pool.last_args("fetchrow", "DELETE FROM tdac.users")
        assert args[0] == 5

    def test_cannot_delete_self(self, client, pool):
        route_users_by_id(pool, {1: make_user_row(id=1)})
        resp = client.delete("/api/auth/users/1", headers=auth_header(1, 0))
        assert resp.status_code == 400
        assert resp.json()["detail"] == "You cannot delete your own account"

    def test_missing_user_404(self, client, pool):
        route_users_by_id(pool, with_target(999, None))
        assert client.delete("/api/auth/users/999", headers=auth_header(1, 0)).status_code == 404

    def test_non_admin_forbidden(self, client, pool):
        route_users_by_id(pool, {5: make_engineer_row()})
        assert client.delete("/api/auth/users/5", headers=auth_header(5, 0)).status_code == 403
