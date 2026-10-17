"""Unit tests for app/auth/security.py — JWT creation/decoding + password hashing."""
import time
from datetime import datetime, timedelta, timezone

import pytest
from jose import JWTError, jwt

from app.auth.security import (
    ALGORITHM,
    SECRET_KEY,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_produces_bcrypt_format(self):
        hashed = hash_password("s3cure-Passw0rd")
        assert hashed.startswith("$2"), "bcrypt hashes start with $2a/$2b/$2y"

    def test_hash_is_salted_every_call(self):
        assert hash_password("same-password") != hash_password("same-password")

    def test_verify_correct_password(self):
        hashed = hash_password("correct-horse")
        assert verify_password("correct-horse", hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-horse")
        assert verify_password("wrong-password", hashed) is False

    @pytest.mark.xfail(strict=True, reason="known bug: pwdlib raises instead of returning False")
    def test_verify_rejects_garbage_hash(self):
        """KNOWN ISSUE (500-risk): verify_password raises ValueError on a
        malformed hash (e.g. truncated/corrupted DB value) instead of
        returning False. In login, that ValueError propagates as HTTP 500.
        Post-fix expectation: returns False so the user gets a clean 401."""
        assert verify_password("x", "not-a-real-hash") is False

    def test_unicode_password_roundtrip(self):
        hashed = hash_password("pässwörd-密码-🔒")
        assert verify_password("pässwörd-密码-🔒", hashed) is True

    def test_max_length_password_rejected(self):
        # bcrypt operates on max 72 bytes; the installed hasher refuses
        # longer input instead of silently truncating. Pin the boundary:
        # 72 bytes round-trips, 73+ raises.
        pw72 = "a" * 72
        hashed = hash_password(pw72)
        assert verify_password(pw72, hashed) is True

        with pytest.raises(ValueError):
            hash_password("a" * 73)

    def test_over_long_password_does_not_verify(self):
        # Login must never turn an impossible credential into a 500. The
        # schemas reject these first, so this is the backstop: a password
        # bcrypt could only have truncated is simply not the stored one.
        hashed = hash_password("a" * 72)
        assert verify_password("a" * 73, hashed) is False

    def test_shared_prefix_beyond_limit_cannot_match(self):
        # The weakness truncate_error would have prevented: bcrypt discards
        # everything past 72 bytes, so these two passwords are identical to
        # it. With the cap enforced they are refused outright instead.
        for tail in ("b" * 20, "z" * 20):
            with pytest.raises(ValueError):
                hash_password("a" * 60 + tail)

    def test_single_definition_of_the_cap(self):
        # The constant used to be copied into two schemas. Assert they all
        # resolve to the one definition in auth.security.
        from app.auth import security
        from app.auth import schemas as auth_schemas
        from app.schemas import user as user_schema

        assert security.BCRYPT_MAX_BYTES == 72
        assert auth_schemas._check_password_bytes is security.check_password_bytes
        assert user_schema._check_password_bytes is security.check_password_bytes


class TestAccessToken:
    def test_roundtrip_preserves_claims(self):
        token = create_access_token({"sub": "42", "token_gen": 3})
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["token_gen"] == 3
        assert payload["type"] == "access"

    def test_has_future_exp(self):
        before = int(datetime.now(timezone.utc).timestamp())
        payload = decode_access_token(create_access_token({"sub": "1"}))
        assert payload["exp"] > before

    def test_custom_expiry_minutes(self):
        payload = decode_access_token(create_access_token({"sub": "1"}, expires_minutes=1))
        assert payload["exp"] <= int((datetime.now(timezone.utc) + timedelta(minutes=1, seconds=5)).timestamp())

    def test_expired_token_rejected(self):
        token = create_access_token({"sub": "1"}, expires_minutes=-1)
        with pytest.raises(JWTError):
            decode_access_token(token)

    def test_tampered_signature_rejected(self):
        token = create_access_token({"sub": "1"})
        header, body, sig = token.split(".")
        tampered = f"{header}.{body}.AAAA{sig[4:]}"
        with pytest.raises(JWTError):
            decode_access_token(tampered)

    def test_wrong_secret_rejected(self):
        token = jwt.encode({"sub": "1", "type": "access", "exp": int(time.time()) + 60},
                          "some-other-secret", algorithm=ALGORITHM)
        with pytest.raises(JWTError):
            decode_access_token(token)

    def test_alg_none_rejected(self):
        # python-jose refuses to ENCODE alg=none, so craft an unsigned JWT by
        # hand: base64url(header).base64url(payload). (empty signature)
        import base64
        import json as _json

        def b64(obj):
            return base64.urlsafe_b64encode(_json.dumps(obj).encode()).rstrip(b"=").decode()

        unsigned = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'sub': '1', 'type': 'access', 'exp': int(time.time()) + 60})}."
        with pytest.raises(JWTError):
            decode_access_token(unsigned)

    def test_garbage_string_rejected(self):
        with pytest.raises(JWTError):
            decode_access_token("garbage.token.here")

    def test_refresh_token_rejected_as_access(self):
        refresh = create_refresh_token({"sub": "1", "token_gen": 0})
        with pytest.raises(JWTError):
            decode_access_token(refresh)

    def test_preexisting_exp_claim_overwritten(self):
        token = create_access_token({"sub": "1", "exp": 1})
        payload = decode_access_token(token)
        assert payload["exp"] != 1


class TestRefreshToken:
    def test_roundtrip_preserves_claims(self):
        payload = decode_refresh_token(create_refresh_token({"sub": "7", "token_gen": 2}))
        assert payload["sub"] == "7"
        assert payload["token_gen"] == 2
        assert payload["type"] == "refresh"

    def test_access_token_rejected_as_refresh(self):
        access = create_access_token({"sub": "1", "token_gen": 0})
        with pytest.raises(JWTError):
            decode_refresh_token(access)

    def test_expired_refresh_rejected(self):
        token = create_refresh_token({"sub": "1"}, expires_days=-1)
        with pytest.raises(JWTError):
            decode_refresh_token(token)

    def test_default_expiry_about_seven_days(self):
        now = datetime.now(timezone.utc)
        payload = decode_refresh_token(create_refresh_token({"sub": "1"}))
        expected_low = now + timedelta(days=7, seconds=-30)
        expected_high = now + timedelta(days=7, seconds=30)
        assert expected_low.timestamp() <= payload["exp"] <= expected_high.timestamp()

    def test_garbage_rejected(self):
        with pytest.raises(JWTError):
            decode_refresh_token("")

    def test_secret_loaded_from_environment(self):
        """FIXED: SECRET_KEY reads JWT_SECRET_KEY from the environment.
        The suite runs with server/.env present (that is the deployed
        shape), so the fallback to the old committed development value
        would mean the secret vanished — fail loudly when that happens."""
        assert SECRET_KEY != "temporary-secret-key"
