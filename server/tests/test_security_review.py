"""Security review pins — from cross-checking the external black-box report
(../TDAC_Authentication_Test_Report.pdf, 2026-09-03) against the code.

Passing tests guard verified-good behavior. xfail(strict) tests pin the FIXED
state for issues confirmed real; the suite turns red when each is fixed.
"""
import re
from pathlib import Path

import pytest

from app.auth import security
from app.auth.schemas import LoginRequest
from app.auth.security import (
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    decode_access_token,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"


class TestVerifiedGood:
    def test_signature_tamper_is_rejected(self):
        """Corrupting payload bytes without re-signing must fail (external
        report claimed a tampered token got 200; current code rejects)."""
        from jose import JWTError

        tok = create_access_token({"sub": "1", "token_gen": 0})
        h, b, s = tok.split(".")
        corrupted = b.replace("I", "J").replace("l", "k") or b[:-2] + "xx"
        with pytest.raises(JWTError):
            decode_access_token(f"{h}.{corrupted}.{s}")

    def test_all_service_sql_is_parameterized(self):
        """Every SQL statement in user_service.py that filters or writes
        (WHERE/VALUES/SET) must use $N bind params and no f-string/format
        interpolation of values (SQL-injection guard). Full-table SELECTs
        without clauses are legitimately parameter-free."""
        src = (APP_DIR / "auth" / "user_service.py").read_text()
        assert "f\"" not in src and "f'" not in src and ".format(" not in src
        for query_block in re.findall(r'"""(.*?)"""', src, re.S):
            if not any(kw in query_block for kw in ("WHERE", "VALUES", "SET")):
                continue  # parameter-free statement (e.g. list all users)
            assert "$" in query_block, f"unparameterized SQL: {query_block[:60]}..."


class TestKnownIssuesPinned:
    def test_schema_disclosure_requires_auth(self, client, pool):
        """NEW ISSUE (info disclosure): /api/test-schemas, /api/test-tables,
        /api/test-user, /api/test-role, /api/testdb expose database schema
        internals with NO authentication (app/main.py:41-157). In production
        this maps the DB for an attacker. Expected: 401."""
        resp = client.get("/api/test-schemas")
        assert resp.status_code in (401, 403)

    @pytest.mark.xfail(strict=True, reason="known issue: /api/test-password is unauthenticated")
    def test_password_probe_requires_auth(self, client, pool):
        """NEW ISSUE: /api/test-password hands any unauthenticated caller a
        real bcrypt hash to take offline. Expected: 401 (or removed)."""
        resp = client.get("/api/test-password")
        assert resp.status_code in (401, 403)

    def test_login_rejects_absurd_password_length(self):
        """LoginRequest.password is capped at bcrypt's 72 BYTE limit.

        pwdlib raises ValueError past 72 bytes and verify_password had no
        guard, so a long password turned login into a 500. The cap turns it
        into a validation error instead. Bytes, not characters: one
        multi-byte character consumes several.
        """
        with pytest.raises(Exception):
            LoginRequest(username="u", password="a" * 10_000)

    def test_login_accepts_exactly_72_bytes(self):
        """The boundary must be inclusive: 72 bytes is still valid."""
        request = LoginRequest(username="u", password="a" * 72)
        assert len(request.password) == 72

    def test_login_rejects_73_bytes(self):
        with pytest.raises(Exception):
            LoginRequest(username="u", password="a" * 73)

    def test_multibyte_password_is_measured_in_bytes(self):
        """A 30-character password of 3-byte characters is 90 bytes and
        must be refused, even though the character count is under 72."""
        with pytest.raises(Exception):
            LoginRequest(username="u", password="\u4e2d" * 30)

    def test_tokens_unique_within_same_second(self):
        """exp is int-seconds and sub/token_gen are stable, so without a
        jti two logins in the same second produced BYTE-IDENTICAL tokens.
        That makes tokens non-unique, so any comparison or revocation that
        relies on identity would treat them as the same token.
        """
        t1 = create_access_token({"sub": "5", "token_gen": 0})
        t2 = create_access_token({"sub": "5", "token_gen": 0})
        assert t1 != t2

    def test_refresh_tokens_unique_within_same_second(self):
        t1 = create_refresh_token({"sub": "5", "token_gen": 0})
        t2 = create_refresh_token({"sub": "5", "token_gen": 0})
        assert t1 != t2

    def test_caller_cannot_smuggle_type_or_exp(self):
        """The claims are set by the issuer, not accepted from the caller,
        so a payload cannot claim to be a refresh or never expire."""
        payload = decode_access_token(
            create_access_token({"sub": "5", "type": "refresh", "exp": 9999999999})
        )
        assert payload["type"] == "access"
        assert payload["exp"] < 9999999999

    def test_forged_token_with_known_secret_is_rejected(self):
        """K5 fixed: SECRET_KEY is externalized to JWT_SECRET_KEY, so the
        old committed value can no longer mint valid admin tokens. A
        token signed with the historical development secret must fail
        verification against the deployed secret."""
        from jose import jwt
        from jose.exceptions import JWTError

        if SECRET_KEY == "temporary-secret-key":
            pytest.fail(
                "JWT_SECRET_KEY leaked out of the environment (missing from "
                ".env): the app fell back to the committed development "
                "secret. Set JWT_SECRET_KEY before running the suite."
            )

        forged = jwt.encode(
            {"sub": "1", "token_gen": 0, "type": "access", "exp": 9999999999},
            "temporary-secret-key",
            algorithm="HS256",
        )
        with pytest.raises(JWTError):
            decode_access_token(forged)
