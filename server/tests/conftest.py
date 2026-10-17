"""Shared test infrastructure for the TDAC server test suite.

Strategy:
- No live PostgreSQL. `FakePool` stands in for asyncpg.Pool and is routed
  per-test by SQL substring, so every HTTP layer + service layer path is
  exercised against deterministic data.
- TestClient is used WITHOUT a context manager so the FastAPI lifespan
  (which would try to connect to a real database) never runs.
"""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import app.database as database
from app.auth.security import create_access_token, hash_password

# Role ids as used by the system (tdac.roles)
ROLE_ADMIN = 1
ROLE_ENGINEER = 2
ROLE_CLIENT = 10


class FakePool:
    """In-memory asyncpg.Pool replacement.

    Program responses with .route(substring, value): the first route whose
    substring appears in the executed SQL wins; unmatched queries return
    None (fetchrow/fetchval) or [] (fetch). Every call is recorded so tests
    can assert on SQL and bind parameters.
    """

    def __init__(self):
        self.routes = []  # (substring, value)
        self.calls = []   # (method, sql, args)
        self.closed = False

    def route(self, substring, value):
        self.routes.append((substring, value))
        return self

    # -- call log helpers -------------------------------------------------
    def calls_with(self, method, substring=""):
        return [c for c in self.calls if c[0] == method and substring in c[1]]

    def last_args(self, method, substring=""):
        matches = self.calls_with(method, substring)
        assert matches, f"no {method} call containing {substring!r} was made"
        return matches[-1][2]

    # -- asyncpg API -------------------------------------------------------
    # A routed value may be a callable; it receives the query bind args and
    # returns the result. This enables arg-aware routing, e.g. returning a
    # different user row for the admin's own auth lookup (id=1) vs the
    # target user lookup (id=5) even though both queries contain "WHERE u.id".
    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        for sub, val in self.routes:
            if sub in sql:
                return val(*args) if callable(val) else val
        return None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        for sub, val in self.routes:
            if sub in sql:
                return val(*args) if callable(val) else val
        return []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        for sub, val in self.routes:
            if sub in sql:
                return val(*args) if callable(val) else val
        return None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        for sub, val in self.routes:
            if sub in sql:
                return val(*args) if callable(val) else val
        return "UPDATE 1"

    async def executemany(self, sql, *args):
        # args = (rows,) for asyncpg's executemany(command, rows) form.
        self.calls.append(("executemany", sql, args))
        for sub, val in self.routes:
            if sub in sql:
                for row in args[0]:
                    if callable(val):
                        val(*row)
                break
        return None

    def transaction(self):
        pool = self

        @asynccontextmanager
        async def _tx():
            pool.calls.append(("begin", "BEGIN", ()))
            try:
                yield pool
            finally:
                pool.calls.append(("commit", "COMMIT", ()))

        return _tx()

    def acquire(self):
        pool = self

        @asynccontextmanager
        async def _ctx():
            yield pool

        return _ctx()

    async def close(self):
        self.closed = True


def make_user_row(**overrides):
    """A tdac.users JOIN tdac.roles row as returned by user_service."""
    row = {
        "id": 1,
        "username": "adminuser",
        # Real bcrypt hash of "test123", computed at import time so that
        # verify_password behaves honestly against it.
        "hashed_password": hash_password("test123"),
        "role_id": ROLE_ADMIN,
        "token_gen": 0,
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "role_name": "admin",
    }
    row.update(overrides)
    return row


def make_engineer_row(**overrides):
    defaults = {
        "id": 5,
        "username": "enguser",
        "role_id": ROLE_ENGINEER,
        "role_name": "engineer",
    }
    defaults.update(overrides)
    return make_user_row(**defaults)


def bearer_token(user_id=1, token_gen=0, **extra_claims):
    return create_access_token(
        {"sub": str(user_id), "token_gen": token_gen, **extra_claims}
    )


def auth_header(user_id=1, token_gen=0, **extra_claims):
    return {"Authorization": f"Bearer {bearer_token(user_id, token_gen, **extra_claims)}"}


def refresh_bearer_token(user_id=1, token_gen=0):
    from app.auth.security import create_refresh_token

    return create_refresh_token({"sub": str(user_id), "token_gen": token_gen})


@pytest.fixture
def pool():
    return FakePool()


@pytest.fixture
def client(monkeypatch, pool):
    """TestClient with app.database.pool replaced by FakePool (no lifespan)."""
    from app.main import app

    # Sample ID allocation runs for every imported CORE/ISPT row. Route it
    # here so import tests do not each have to remember it; an unrouted
    # fetchrow returns None and _allocate_sample_id would raise.
    pool.route(
        '"tdac"."SAMPLE_ID_COUNTER"',
        lambda *args: {"LAST_NUMBER": 1},
    )

    monkeypatch.setattr(database, "pool", pool)
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_row():
    return make_user_row()


@pytest.fixture
def admin_headers():
    return auth_header(user_id=1, token_gen=0)


def route_users_by_id(pool, rows_by_id: dict):
    """Arg-aware routing for get_user_by_id: maps user_id -> row (or None)."""
    pool.route("WHERE u.id", lambda *args: rows_by_id.get(args[0]))


def route_users_by_username(pool, rows_by_username: dict):
    """Arg-aware routing for get_user_by_username: maps username -> row."""
    pool.route("WHERE u.username = $1", lambda *args: rows_by_username.get(args[0]))
