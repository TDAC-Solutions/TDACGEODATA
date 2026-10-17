"""POST /api/auth/login — credential flows, ordering, and response shape."""
import pytest

from tests.conftest import make_user_row, route_users_by_username


def route_username(pool, rows_by_username):
    route_users_by_username(pool, rows_by_username)


class TestLoginSuccess:
    def test_valid_credentials_return_tokens(self, client, pool):
        route_username(pool, {"adminuser": make_user_row()})
        resp = client.post("/api/auth/login", json={"username": "adminuser", "password": "test123"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert isinstance(body["access_token"], str) and body["access_token"].count(".") == 2
        assert isinstance(body["refresh_token"], str) and body["refresh_token"].count(".") == 2

    def test_tokens_carry_sub_and_token_gen(self, client, pool):
        from app.auth.security import decode_access_token, decode_refresh_token

        route_username(pool, {"u": make_user_row(id=9, token_gen=4)})
        body = client.post("/api/auth/login", json={"username": "u", "password": "test123"}).json()
        access = decode_access_token(body["access_token"])
        refresh = decode_refresh_token(body["refresh_token"])
        assert access["sub"] == "9" and access["token_gen"] == 4
        assert refresh["sub"] == "9" and refresh["token_gen"] == 4

    def test_login_with_known_password_succeeds(self, client, pool):
        """The default row's hash is bcrypt of 'test123' (see conftest)."""
        route_username(pool, {"u": make_user_row()})
        resp = client.post("/api/auth/login", json={"username": "u", "password": "test123"})
        assert resp.status_code == 200


class TestLoginFailures:
    def test_unknown_username_401(self, client, pool):
        resp = client.post("/api/auth/login", json={"username": "ghost", "password": "x"})
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"]

    def test_wrong_password_401(self, client, pool):
        route_username(pool, {"u": make_user_row()})
        resp = client.post("/api/auth/login", json={"username": "u", "password": "wrong"})
        assert resp.status_code == 401

    def test_missing_fields_422(self, client, pool):
        assert client.post("/api/auth/login", json={"username": "u"}).status_code == 422
        assert client.post("/api/auth/login", json={"password": "p"}).status_code == 422
        assert client.post("/api/auth/login", json={}).status_code == 422
        assert client.post("/api/auth/login", content="not json").status_code == 422

    def test_empty_strings_still_hit_db_lookup(self, client, pool):
        resp = client.post("/api/auth/login", json={"username": "", "password": ""})
        assert resp.status_code == 401
        assert pool.calls_with("fetchrow", "WHERE u.username")


class TestLoginKnownIssues:
    def test_inactive_user_message_is_wrong(self, client, pool):
        """PIN (router.py login): inactive accounts are rejected with the
        correct message before password verification (older builds said
        the opposite; this pins the fixed behavior)."""
        route_username(pool, {"u": make_user_row(is_active=False)})
        resp = client.post("/api/auth/login", json={"username": "u", "password": "p"})
        assert resp.status_code == 403
        assert resp.json()["detail"] == "User account is inactive"

    @pytest.mark.xfail(strict=True, reason="known bug: status checked before password")
    def test_password_checked_before_active_status(self, client, pool):
        """KNOWN ISSUE (router.py login, still present): inactive users are
        rejected with 403 before the password is validated, which leaks
        that an account exists and is disabled to anyone who knows the
        username. Desired post-fix behavior asserted here; fails strictly
        while the bug exists."""
        route_username(pool, {"u": make_user_row(is_active=False)})
        resp = client.post("/api/auth/login", json={"username": "u", "password": "definitely-wrong"})
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Invalid username or password"

    @pytest.mark.xfail(strict=True, reason="known bug")
    def test_error_messages_not_case_consistent(self, client, pool):
        """KNOWN ISSUE (cosmetic, router.py:38 vs 54): unknown username says
        'Invalid Username or password' but wrong password says 'Invalid
        username or password'."""
        unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "x"}).json()["detail"]
        route_username(pool, {"u": make_user_row()})
        wrongpw = client.post("/api/auth/login", json={"username": "u", "password": "x"}).json()["detail"]
        assert unknown == wrongpw == "Invalid username or password"
