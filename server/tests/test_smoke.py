"""Smoke test: verifies the harness itself works before the full suite runs."""
from app.auth.security import hash_password, verify_password

from tests.conftest import auth_header, make_user_row


def test_app_boots_and_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Tdac api is running"}


def test_fake_pool_receives_queries(client, pool):
    pool.route("WHERE u.id", make_user_row())
    client.get("/api/testdb", headers=auth_header())
    assert pool.calls_with("fetchval", "SELECT NOW()")


def test_real_bcrypt_roundtrip():
    h = hash_password("smoke-pass-123")
    assert verify_password("smoke-pass-123", h) is True
    assert verify_password("wrong", h) is False


def test_auth_header_helper_produces_decodable_token(client, pool):
    pool.route("WHERE u.id", make_user_row())
    resp = client.get("/api/auth/home", headers=auth_header(user_id=1))
    assert resp.status_code == 200
