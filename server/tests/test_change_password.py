"""Self-service password change (POST /api/auth/change-password).

The endpoint is the backend half of the Topbar account menu: verify the
current password, rotate the hash, bump token_gen so every OTHER session
dies, and return fresh tokens so THIS session survives.
"""
import pytest

from app.auth.security import verify_password
from tests.conftest import auth_header, make_user_row


def change_body(current="test123", next_pw="newpass123", confirm=None):
    return {
        "current_password": current,
        "new_password": next_pw,
        "confirm_password": confirm if confirm is not None else next_pw,
    }


class TestChangePasswordValidation:
    def test_requires_auth(self, client, pool):
        resp = client.post("/api/auth/change-password", json=change_body())
        # Version-dependent code (401/403); see test_dependencies.
        assert resp.status_code in (401, 403)

    def test_mismatched_confirm_rejected_before_db(self, client, pool):
        route_id = pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/auth/change-password",
            json=change_body(confirm="different1"),
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 422
        # Nothing written: the schema validator rejects before the pool
        # is touched beyond the auth lookup.
        assert not pool.calls_with("execute", "token_gen = $3")

    def test_same_password_rejected(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/auth/change-password",
            json=change_body(current="test123", next_pw="test123"),
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 400
        assert "differ" in resp.json()["detail"]
        assert not pool.calls_with("execute", "hashed_password = $2")

    def test_wrong_current_password_rejected(self, client, pool):
        pool.route("WHERE u.id", make_user_row())
        resp = client.post(
            "/api/auth/change-password",
            json=change_body(current="wrong-password"),
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 401
        assert "incorrect" in resp.json()["detail"].lower()
        # No password write when proof fails.
        assert not pool.calls_with("execute", "hashed_password = $2")


class TestChangePasswordCommit:
    def test_updates_hash_and_bumps_gen(self, client, pool):
        pool.route("WHERE u.id", make_user_row(token_gen=0))
        resp = client.post(
            "/api/auth/change-password",
            json=change_body(),
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] and body["refresh_token"]

        args = pool.last_args("execute", "hashed_password = $2")
        # (user_id, new_hash, new_gen)
        assert args[0] == 1
        assert verify_password("newpass123", args[1]) is True
        assert args[2] == 1  # token_gen 0 -> 1

    def test_fresh_tokens_carry_new_gen_and_old_dies(self, client, pool):
        # Row state is mutable: after the change the same "WHERE u.id"
        # lookup must return gen 1, so the OLD token (gen 0) is revoked.
        state = {"row": make_user_row(token_gen=0)}

        def lookup(user_id):
            return state["row"]

        pool.route("WHERE u.id", lookup)

        resp = client.post(
            "/api/auth/change-password",
            json=change_body(),
            headers=auth_header(1, 0),
        )
        assert resp.status_code == 200

        state["row"] = make_user_row(token_gen=1)

        old = client.get(
            "/api/auth/home",
            headers=auth_header(1, 0),
        )
        assert old.status_code == 401

        # The fresh access token decodes with the new gen.
        from app.auth.security import decode_access_token

        claims = decode_access_token(resp.json()["access_token"])
        assert claims["token_gen"] == 1
        assert claims["type"] == "access"

        from app.auth.security import decode_refresh_token

        refresh = decode_refresh_token(resp.json()["refresh_token"])
        assert refresh["token_gen"] == 1
        assert refresh["type"] == "refresh"

    def test_inactive_user_cannot_change_password(self, client, pool):
        pool.route("WHERE u.id", make_user_row(is_active=False))
        resp = client.post(
            "/api/auth/change-password",
            json=change_body(),
            headers=auth_header(1, 0),
        )
        # get_current_user rejects inactive accounts before the endpoint.
        assert resp.status_code == 401
        assert not pool.calls_with("execute", "hashed_password = $2")


def route_id(pool, row):
    pool.route("WHERE u.id", row)
