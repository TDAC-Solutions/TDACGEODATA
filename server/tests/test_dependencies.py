"""Auth dependency chain: get_current_user / get_current_admin.

Exercised through /api/auth/home (any user) and /api/auth/admin-test (admin
only) — the same dependency code every protected endpoint uses.
"""
from app.auth.security import create_access_token

from tests.conftest import auth_header, make_user_row, make_engineer_row


def route_id(pool, row):
    pool.route("WHERE u.id", row)


class TestGetCurrentUser:
    def test_valid_token_returns_user_context(self, client, pool):
        route_id(pool, make_user_row(id=1, username="adminuser"))
        resp = client.get("/api/auth/home", headers=auth_header(1, 0))
        assert resp.status_code == 200
        assert resp.json() == {
            "message": "Welcome to TDAC",
            "user": {"id": 1, "username": "adminuser", "role": "admin"},
        }

    def test_missing_authorization_header_rejected(self, client, pool):
        resp = client.get("/api/auth/home")
        # HTTPBearer's missing-header code differs across fastapi/starlette
        # versions (403 historically, 401 on newer releases). The contract
        # under test is "rejected without credentials", not the exact code.
        assert resp.status_code in (401, 403)

    def test_garbage_token_rejected(self, client, pool):
        resp = client.get("/api/auth/home", headers={"Authorization": "Bearer not.a.jwt"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid or expired token"

    def test_expired_token_rejected(self, client, pool):
        token = create_access_token({"sub": "1", "token_gen": 0}, expires_minutes=-1)
        resp = client.get("/api/auth/home", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_refresh_token_rejected_as_bearer(self, client, pool):
        from tests.conftest import refresh_bearer_token

        resp = client.get("/api/auth/home", headers={"Authorization": f"Bearer {refresh_bearer_token(1, 0)}"})
        assert resp.status_code == 401

    def test_token_without_sub_rejected(self, client, pool):
        token = create_access_token({"token_gen": 0})
        resp = client.get("/api/auth/home", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid authentication token"

    def test_non_numeric_sub_rejected(self, client, pool):
        token = create_access_token({"sub": "abc", "token_gen": 0})
        resp = client.get("/api/auth/home", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

    def test_deleted_user_rejected(self, client, pool):
        route_id(pool, None)
        resp = client.get("/api/auth/home", headers=auth_header(1, 0))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User no longer exists"

    def test_inactive_user_rejected(self, client, pool):
        route_id(pool, make_user_row(id=1, is_active=False))
        resp = client.get("/api/auth/home", headers=auth_header(1, 0))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "User account is inactive"

    def test_stale_token_after_logout_rejected(self, client, pool):
        # DB token_gen was bumped (logout) but the JWT still carries the old gen
        route_id(pool, make_user_row(id=1, token_gen=9))
        resp = client.get("/api/auth/home", headers=auth_header(1, 0))
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Token has been revoked"

    def test_forwarded_user_row_contains_role_fields(self, client, pool):
        route_id(pool, make_user_row())
        resp = client.get("/api/auth/admin-test", headers=auth_header(1, 0))
        assert resp.status_code == 200
        user = resp.json()["user"]
        for key in ("id", "username", "role_id", "role_name", "is_active", "token_gen"):
            assert key in user


class TestGetCurrentAdmin:
    def test_admin_passes(self, client, pool):
        route_id(pool, make_user_row(id=1, role_name="admin"))
        resp = client.get("/api/auth/admin-test", headers=auth_header(1, 0))
        assert resp.status_code == 200
        assert resp.json()["message"] == "Welcome Admin"

    def test_engineer_forbidden(self, client, pool):
        route_id(pool, make_engineer_row())
        resp = client.get("/api/auth/admin-test", headers=auth_header(5, 0))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "Admin access required"

    def test_no_token_rejected(self, client, pool):
        # Version-dependent code (401/403); see TestGetCurrentUser.
        assert client.get("/api/auth/admin-test").status_code in (401, 403)

    def test_unknown_path_404(self, client, pool):
        assert client.get("/api/auth/does-not-exist").status_code == 404
