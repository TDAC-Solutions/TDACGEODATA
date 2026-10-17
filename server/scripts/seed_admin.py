"""Seed the local admin account (idempotent).

Creates/updates the "admin" user with the ADMIN_PASSWORD (default
admin@123) so the local Termux setup is testable immediately. Role id 1
is the application's fixed admin role (see scripts/init_local_db.sql).
"""
import asyncio
import os
import sys

# Run from anywhere: make "app" importable like every server command.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import database
from app.auth.security import hash_password


async def main():
    username = os.getenv("ADMIN_USERNAME", "admin")
    password = os.getenv("ADMIN_PASSWORD", "admin@123")

    await database.connect_to_database()
    try:
        async with database.pool.acquire() as connection:
            role = await connection.fetchval(
                "SELECT id FROM tdac.roles WHERE name = 'admin'"
            )
            if role is None:
                print("Admin role is missing; run scripts/init_local_db.sql first.")
                return

            await connection.execute(
                """
                INSERT INTO tdac.users (username, hashed_password, role_id, is_active)
                VALUES ($1, $2, $3, TRUE)
                ON CONFLICT (username)
                DO UPDATE SET hashed_password = EXCLUDED.hashed_password,
                              is_active = TRUE
                """,
                username,
                hash_password(password),
                role,
            )
            print(f"Admin account ready: {username} / {password}")
    finally:
        await database.close_database()


if __name__ == "__main__":
    asyncio.run(main())
