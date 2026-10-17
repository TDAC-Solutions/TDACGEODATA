"""Infrastructure: app/database.py, FastAPI lifespan, app/create_admin.py.

Real PostgreSQL is never touched: asyncpg.create_pool is monkeypatched to
return a FakePool, and create_admin's stdin (input/getpass) is monkeypatched.
"""
import asyncio

import pytest

import app.create_admin as create_admin_mod
import app.database as database
from app.main import app

from tests.conftest import FakePool, make_user_row


@pytest.fixture
def fake_asyncpg(monkeypatch):
    """Route app.database's pool creation to a FakePool instance.

    Tests can pre-seed SQL routes via fake_asyncpg["routes"] BEFORE the code
    under test creates the pool; each seeded (substring, value) pair is
    applied to every pool created through the patched asyncpg.create_pool.
    """
    holder = {"routes": []}

    async def fake_create_pool(**kwargs):
        holder["config"] = kwargs
        p = FakePool()
        for sub, val in holder["routes"]:
            p.route(sub, val)
        holder["pool"] = p
        return p

    monkeypatch.setattr(database.asyncpg, "create_pool", fake_create_pool)
    return holder


class TestDatabaseModule:
    def test_connect_reads_env_at_import_time(self, fake_asyncpg, monkeypatch):
        """DATABASE_CONFIG is frozen at module import (database.py:8-14), so
        the honest test sets env vars and RELOADS the module, then connects."""
        import importlib

        monkeypatch.setenv("DB_HOST", "dbhost")
        monkeypatch.setenv("DB_PORT", "5433")
        monkeypatch.setenv("DB_NAME", "ags42_data")
        monkeypatch.setenv("DB_USER", "dbuser")
        monkeypatch.setenv("DB_PASSWORD", "dbpass")
        importlib.reload(database)
        asyncio.run(database.connect_to_database())
        cfg = fake_asyncpg["config"]
        assert cfg["host"] == "dbhost"
        assert cfg["port"] == 5433
        assert cfg["database"] == "ags42_data"
        assert cfg["user"] == "dbuser"
        assert cfg["password"] == "dbpass"
        assert cfg["min_size"] == 1 and cfg["max_size"] == 10
        assert database.pool is fake_asyncpg["pool"]

    def test_connect_defaults_without_env(self, fake_asyncpg, monkeypatch):
        import importlib

        import dotenv

        for var in ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"):
            monkeypatch.delenv(var, raising=False)
        # The module re-runs load_dotenv() on reload, which walks up from
        # app/database.py, finds server/.env and re-sets DB_HOST —
        # defeating the delenv above. This test is about the no-env
        # DEFAULTS, so the .env loader is neutralized for the reload.
        monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
        importlib.reload(database)
        asyncio.run(database.connect_to_database())
        cfg = fake_asyncpg["config"]
        assert cfg["host"] == "localhost"
        assert cfg["port"] == 5432
        assert cfg["database"] is None  # dev-only default; no crash on import

    def test_close_closes_pool(self, fake_asyncpg):
        asyncio.run(database.connect_to_database())
        p = database.pool
        asyncio.run(database.close_database())
        assert p.closed is True

    def test_close_with_no_pool_is_noop(self):
        database.pool = None
        asyncio.run(database.close_database())  # must not raise


class TestLifespan:
    def test_lifespan_connects_then_closes(self, fake_asyncpg, capsys):
        async def scenario():
            async with app.router.lifespan_context(app):
                assert database.pool is fake_asyncpg["pool"]
            assert fake_asyncpg["pool"].closed is True

        asyncio.run(scenario())
        out = capsys.readouterr().out
        assert "Connecting to database..." in out
        assert "Database connected." in out
        assert "Database connection closed." in out


class TestCreateAdminScript:
    def _run(self, monkeypatch, username, password):
        monkeypatch.setattr("builtins.input", lambda *a: username)
        monkeypatch.setattr(create_admin_mod, "getpass", lambda *a: password)

    def test_successful_admin_creation(self, fake_asyncpg, monkeypatch, capsys):
        self._run(monkeypatch, "newadmin", "strongpass1")
        fake_asyncpg["routes"].append(("tdac.roles", {"id": 1}))  # role exists
        fake_asyncpg["routes"].append(("tdac.users", None))       # no duplicate
        asyncio.run(create_admin_mod.create_admin())
        p = fake_asyncpg["pool"]  # pool exists once the script connected
        out = capsys.readouterr().out
        assert "Admin user created successfully." in out
        # INSERT must carry a bcrypt hash, not plaintext
        insert_calls = p.calls_with("execute", "INSERT INTO tdac.users")
        assert insert_calls, "expected an INSERT"
        args = insert_calls[0][2]
        assert args[0] == "newadmin"
        assert args[1].startswith("$2") and args[1] != "strongpass1"
        assert args[2] == 1
        assert p.closed is True, "script must close the pool in finally"

    def test_missing_admin_role_aborts(self, fake_asyncpg, monkeypatch, capsys):
        self._run(monkeypatch, "newadmin", "strongpass1")
        asyncio.run(create_admin_mod.create_admin())
        p = fake_asyncpg["pool"]
        assert "Admin role does not exist." in capsys.readouterr().out
        assert not p.calls_with("execute", "INSERT INTO tdac.users")

    def test_duplicate_username_aborts(self, fake_asyncpg, monkeypatch, capsys):
        self._run(monkeypatch, "existing", "strongpass1")
        fake_asyncpg["routes"].append(("tdac.roles", {"id": 1}))
        fake_asyncpg["routes"].append(("tdac.users", make_user_row(id=3)))  # duplicate!
        asyncio.run(create_admin_mod.create_admin())
        p = fake_asyncpg["pool"]
        assert "Username already exists." in capsys.readouterr().out
        assert not p.calls_with("execute", "INSERT INTO tdac.users")

    def test_pool_closed_even_on_error(self, fake_asyncpg, monkeypatch):
        self._run(monkeypatch, "a", "b")

        async def boom(*a, **k):
            raise RuntimeError("db exploded")

        # Break only the role lookup; pool must still close via finally.
        original = FakePool.fetchrow

        async def fetchrow_boom(self, sql, *args):
            if "tdac.roles" in sql:
                raise RuntimeError("db exploded")
            return await original(self, sql, *args)

        monkeypatch.setattr(FakePool, "fetchrow", fetchrow_boom)
        with pytest.raises(RuntimeError):
            asyncio.run(create_admin_mod.create_admin())
        assert fake_asyncpg["pool"].closed is True
