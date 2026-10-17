# database.py
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv()

DATABASE_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

pool: asyncpg.Pool | None = None


def _startup_hint(error: Exception) -> str:
    """Turn a connection failure into something the operator can act on.

    A bare ConnectionRefusedError traceback says nothing about the actual
    problem, and this runs on every device the app is deployed to, where the
    usual cause is simply that the local PostgreSQL service is not running.
    """
    host = DATABASE_CONFIG["host"]
    port = DATABASE_CONFIG["port"]

    if isinstance(error, ConnectionRefusedError):
        return (
            f"Cannot reach PostgreSQL at {host}:{port} -- nothing is "
            "listening on that port.\n"
            f"  Linux:  sudo pg_ctlcluster 18 main start\n"
            f"  macOS:  brew services start postgresql\n"
            f"  Docker: docker compose up -d db\n"
            "  Check with: pg_isready -h " + str(host) + " -p " + str(port)
        )

    if isinstance(error, FileNotFoundError):
        return (
            "Could not find the .env file next to app/database.py. "
            "DB_NAME, DB_USER and DB_PASSWORD come from it."
        )

    name = type(error).__name__
    if "Authentication" in name:
        return (
            f"PostgreSQL rejected the credentials for user "
            f"{DATABASE_CONFIG['user']!r} on {host}. Check DB_USER and "
            "DB_PASSWORD in .env."
        )

    return f"{name}: {error}"


async def connect_to_database():
    global pool

    try:
        pool = await asyncpg.create_pool(
            **DATABASE_CONFIG,
            min_size=1,
            max_size=10,
        )
    except Exception as error:
        raise RuntimeError(
            "Database connection failed.\n"
            + _startup_hint(error)
        ) from error


async def close_database():
    global pool

    if pool:
        await pool.close()