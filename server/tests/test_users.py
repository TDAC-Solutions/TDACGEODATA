"""Admin user management: POST/GET/PUT/PATCH/DELETE /api/auth/users[...]."""
import pytest

from tests.conftest import (
    ROLE_CLIENT,
    ROLE_ENGINEER,
    auth_header,
    make_engineer_row,
    make_user_row,
)


def route_username(pool, row_or_none):
    pool.route("WHERE u.username = $1", row_or_none)


def route_id(pool, row_or_none):
    pool.route("WHERE u.id", row_or_none)


def route_insert(pool, row):
    pool.route("INSERT INTO tdac.users", row)


class TestCreateUser:
    def test_admin_creates_engineer(self, client, pool):
        route_id(pool, make_user_row())
        route_username(pool, None)
        route_insert(pool, make_engineer_row(id=42))
        resp = client.post(
            "/api/auth/users",
            json={"username": "neweng", "password": "longenough1", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "User created successfully"
        assert body["user"] == {"id": 42, "username": "enguser", "role_id": ROLE_ENGINEER}

    def test_password_is_hashed_not_stored_plaintext(self, client, pool):
        route_id(pool, make_user_row())
        route_username(pool, None)
        route_insert(pool, make_engineer_row(id=42))
        client.post(
            "/api/auth/users",
            json={"username": "neweng", "password": "longenough1", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        args = pool.last_args("fetchrow", "INSERT INTO tdac.users")
        assert args[0] == "neweng"
        assert args[1].startswith("$2"), "stored secret must be a bcrypt hash"
        assert args[1] != "longenough1"

    def test_rejects_disallowed_role_ids(self, client, pool):
        route_id(pool, make_user_row())
        for bad_role in (1, 3, 99, 0, -1):
            resp = client.post(
                "/api/auth/users",
                json={"username": "someone", "password": "longenough1", "role_id": bad_role},
                headers=auth_header(1, 0),
            )
            assert resp.status_code == 400, f"role_id={bad_role}"
            assert resp.json()["detail"] == "Only engineer or client accounts can be created"

    def test_duplicate_username_409(self, client, pool):
        route_id(pool, make_user_row())
        route_username(pool, make_user_row(id=7, username="taken"))
        resp = client.post(
            "/api/auth/users",
            json={"username": "taken", "password": "longenough1", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 409

    def test_validation_short_username_422(self, client, pool):
        route_id(pool, make_user_row())
        resp = client.post(
            "/api/auth/users",
            json={"username": "ab", "password": "longenough1", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 422

    def test_validation_short_password_422(self, client, pool):
        route_id(pool, make_user_row())
        resp = client.post(
            "/api/auth/users",
            json={"username": "validname", "password": "short", "role_id": ROLE_ENGINEER},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 422

    def test_validation_missing_fields_422(self, client, pool):
        route_id(pool, make_user_row())
        assert client.post("/api/auth/users", json={}, headers=auth_header(1, 0)).status_code == 422

    def test_non_admin_cannot_create(self, client, pool):
        route_id(pool, make_engineer_row())
        resp = client.post(
            "/api/auth/users",
            json={"username": "neweng", "password": "longenough1", "role_id": ROLE_ENGINEER},
            headers=auth_header(5, 0),
        )
        assert resp.status_code == 403

    def test_service_rejects_admin_role_via_sql_guard(self, client, pool):
        """The INSERT..SELECT..WHERE r.name IN ('engineer','client') is the
        second line of defense: role_id=1/10-only check at the router plus the
        SQL guard. If both missed, user would be None -> 500. Here the router
        check must fire first, so role_id=1 never reaches SQL."""
        route_id(pool, make_user_row())
        resp = client.post(
            "/api/auth/users",
            json={"username": "hax", "password": "longenough1", "role_id": 1},
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 400
        assert not pool.calls_with("fetchrow", "INSERT INTO tdac.users")


class TestListUsers:
    def test_admin_lists_all_users(self, client, pool):
        route_id(pool, make_user_row())
        pool.route(
            "ORDER BY u.id",
            [
                make_user_row(id=1, username="adminuser"),
                make_engineer_row(id=5),
            ],
        )
        resp = client.get("/api/auth/users", headers=auth_header(1, 0))
        assert resp.status_code == 200
        users = resp.json()["users"]
        assert len(users) == 2
        assert users[0]["role_name"] == "admin"
        assert users[1]["username"] == "enguser"
        for u in users:
            assert "hashed_password" not in u, "hash must never be serialized"

    def test_empty_user_table(self, client, pool):
        route_id(pool, make_user_row())
        resp = client.get("/api/auth/users", headers=auth_header(1, 0))
        assert resp.status_code == 200
        assert resp.json() == {"users": []}

    def test_non_admin_forbidden(self, client, pool):
        route_id(pool, make_engineer_row())
        assert client.get("/api/auth/users", headers=auth_header(5, 0)).status_code == 403


class TestGetSingleUser:
    def test_admin_gets_user_by_id(self, client, pool):
        """PIN: the single-user endpoint returns the target row without the
        password hash (older builds crashed with a NameError here)."""
        from tests.conftest import route_users_by_id

        route_users_by_id(pool, {1: make_user_row(), 5: make_engineer_row(id=5)})
        resp = client.get("/api/auth/users/5", headers=auth_header(1, 0))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == 5
        assert "hashed_password" not in body

    def test_missing_user_404(self, client, pool):
        from tests.conftest import route_users_by_id

        route_users_by_id(pool, {1: make_user_row(), 999: None})
        resp = client.get("/api/auth/users/999", headers=auth_header(1, 0))
        assert resp.status_code == 404

    def test_non_admin_forbidden(self, client, pool):
        route_id(pool, make_engineer_row())
        assert client.get("/api/auth/users/5", headers=auth_header(5, 0)).status_code == 403

    def test_non_integer_id_422(self, client, pool):
        route_id(pool, make_user_row())
        assert client.get("/api/auth/users/notanint", headers=auth_header(1, 0)).status_code == 422
