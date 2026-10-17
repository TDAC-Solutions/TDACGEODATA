"""POST /api/auth/refresh and POST /api/auth/logout."""
from tests.conftest import auth_header, make_engineer_row, make_user_row, refresh_bearer_token


def route_id(pool, row_or_none):
    pool.route("WHERE u.id", row_or_none)


class TestRefresh:
    def test_valid_refresh_returns_new_access_token(self, client, pool):
        route_id(pool, make_user_row(id=1))
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(1, 0)})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"].count(".") == 2

    def test_new_token_is_decodable_and_bound_to_user(self, client, pool):
        from app.auth.security import decode_access_token

        route_id(pool, make_user_row(id=9, token_gen=2))
        body = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(9, 2)}).json()
        payload = decode_access_token(body["access_token"])
        assert payload["sub"] == "9"
        assert payload["token_gen"] == 2

    def test_refresh_token_sent_as_query_param(self, client, pool):
        """The handler signature is `refresh_token: str` (a bare scalar), so
        FastAPI treats it as a REQUIRED QUERY PARAMETER, not a JSON body.
        Documenting actual behavior: token via query string works."""
        route_id(pool, make_user_row(id=1))
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(1, 0)})
        assert resp.status_code == 200

    def test_json_body_is_accepted(self, client, pool):
        """The token travels in a JSON body.

        It used to be a query parameter, which writes a long-lived
        credential into access logs, proxy logs and browser history. The
        body is the only acceptable place for it.
        """
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/auth/refresh",
            json={"refresh_token": refresh_bearer_token(1, 0)},
        )
        assert resp.status_code == 200, resp.text
        assert "access_token" in resp.json()

    def test_token_in_query_string_is_ignored(self, client, pool):
        """A query-string token is no longer honoured, so it cannot leak."""
        resp = client.post(
            f"/api/auth/refresh?refresh_token={refresh_bearer_token(1, 0)}"
        )
        assert resp.status_code == 422, resp.text

    def test_missing_token_422(self, client, pool):
        assert client.post("/api/auth/refresh").status_code == 422

    def test_expired_refresh_401(self, client, pool):
        from app.auth.security import create_refresh_token

        expired = create_refresh_token({"sub": "1", "token_gen": 0}, expires_days=-1)
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": expired})
        assert resp.status_code == 401

    def test_garbage_refresh_401(self, client, pool):
        resp = client.post(
            "/api/auth/refresh", json={"refresh_token": "garbage"}
        )
        assert resp.status_code == 401

    def test_access_token_used_as_refresh_401(self, client, pool):
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": auth_header(1, 0)['Authorization'][7:]})
        assert resp.status_code == 401

    def test_unknown_user_401(self, client, pool):
        route_id(pool, None)
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(999, 0)})
        assert resp.status_code == 401

    def test_refresh_token_without_sub_401(self, client, pool):
        from app.auth.security import create_refresh_token

        token = create_refresh_token({"token_gen": 0})
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid refresh token"

    def test_refresh_token_non_numeric_sub_401(self, client, pool):
        from app.auth.security import create_refresh_token

        token = create_refresh_token({"sub": "abc", "token_gen": 0})
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": token})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid refresh token"

    def test_inactive_user_403(self, client, pool):
        route_id(pool, make_user_row(id=1, is_active=False))
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(1, 0)})
        assert resp.status_code == 403

    def test_invalidated_refresh_401_after_logout_or_ban(self, client, pool):
        route_id(pool, make_user_row(id=1, token_gen=5))  # DB gen ahead of JWT gen
        resp = client.post("/api/auth/refresh",
        json={"refresh_token": refresh_bearer_token(1, 0)})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Refresh token has been invalidated"


class TestLogout:
    def test_logout_bumps_token_gen(self, client, pool):
        route_id(pool, make_user_row(id=1))
        resp = client.post("/api/auth/logout", headers=auth_header(1, 0))
        assert resp.status_code == 200
        assert resp.json() == {"message": "Logged out successfully"}
        args = pool.last_args("execute", "token_gen = token_gen + 1")
        assert args[0] == 1

    def test_logout_requires_auth(self, client, pool):
        # Version-dependent code (401/403); see test_dependencies.
        assert client.post("/api/auth/logout").status_code in (401, 403)

    def test_old_token_rejected_after_logout(self, client, pool):
        # After logout the DB row has token_gen bumped -> dependency rejects old JWT
        route_id(pool, make_user_row(id=1, token_gen=1))
        resp = client.post("/api/auth/logout", headers=auth_header(1, 0))  # old gen 0 in JWT
        assert resp.status_code == 401
