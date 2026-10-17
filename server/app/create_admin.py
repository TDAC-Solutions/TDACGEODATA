import asyncio
from getpass import getpass

from app import database
from app.auth.security import hash_password


async def create_admin():

    username = input("Admin username: ")
    password = getpass("Admin password: ")

    await database.connect_to_database()

    try:
        async with database.pool.acquire() as connection:

            role = await connection.fetchrow(
                """
                SELECT id
                FROM tdac.roles
                WHERE name = 'admin'
                """
            )

            if role is None:
                print("Admin role does not exist.")
                return

            existing_user = await connection.fetchrow(
                """
                SELECT id
                FROM tdac.users
                WHERE username = $1
                """,
                username
            )

            if existing_user:
                print("Username already exists.")
                return

            hashed_password = hash_password(password)

            await connection.execute(
                """
                INSERT INTO tdac.users
                    (username, hashed_password, role_id, token_gen, created_at)
                VALUES
                    ($1, $2, $3, 0, NOW())
                """,
                username,
                hashed_password,
                role["id"]
            )

            print("Admin user created successfully.")

    finally:
        await database.close_database()


if __name__ == "__main__":
    asyncio.run(create_admin())