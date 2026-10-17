from app import database

async def get_user_by_username(username: str):
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            SELECT 
            u.id, 
            u.username, 
            u.hashed_password, 
            u.role_id, 
            u.token_gen, 
            u.is_active,
            u.created_at,
            r.name AS role_name, 
            r.permissions
            FROM tdac.users u JOIN tdac.roles r ON u.role_id = r.id
            WHERE u.username = $1
            """,
            username
        )
        return user

async def get_user_by_id(user_id: int):
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            SELECT
            u.id,
            u.username,
            u.hashed_password,
            u.role_id,
            u.token_gen,
            u.is_active,
            u.created_at,
            r.name AS role_name
            FROM tdac.users u
            JOIN tdac.roles r
            ON u.role_id = r.id
            WHERE u.id = $1
            """,user_id
        )

    return user

async def get_all_users():
    async with database.pool.acquire() as connection:
        users = await connection.fetch(
            """
            SELECT 
            u.id,
            u.username,
            u.role_id,
            u.is_active,
            u.created_at,
            r.name AS role_name
            FROM tdac.users u
            JOIN tdac.roles r
            ON u.role_id = r.id
            ORDER BY u.id
            """
        )
        return users

async def create_user(
        username: str,
        hashed_password: str,
        role_id: int
):
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            INSERT INTO tdac.users(
                username,
                hashed_password,
                role_id,
                token_gen,
                is_active,
                created_at
            )
            SELECT
                $1, $2, r.id, 0,TRUE,NOW()
            FROM tdac.roles r
            WHERE r.id = $3
                AND r.name IN ('engineer','client')
            RETURNING
                id,
                username,
                role_id,
                token_gen,
                created_at
            """,
            username,
            hashed_password,
            role_id
        )
    return user

async def update_user(
        user_id: int,
        username: str | None =  None,
        hashed_password: str | None = None,
        role_id: int | None = None
):
    """Update a user's profile.

    token_gen is bumped only when the change is security-relevant, i.e. a
    new password or a new role. A username-only edit used to force every
    signed-in session of that user to re-login, which read as a bug rather
    than a security measure.
    """
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            UPDATE tdac.users
            SET
                username = COALESCE($2, username),
                hashed_password = COALESCE($3, hashed_password),
                role_id = COALESCE($4, role_id),
                token_gen = token_gen + CASE
                    WHEN $3 IS NOT NULL OR $4 IS NOT NULL THEN 1
                    ELSE 0
                END
            WHERE id = $1
            RETURNING 
                id, 
                username, 
                role_id,
                is_active,
                created_at
            """, 
            user_id,
            username,
            hashed_password,
            role_id
        ) 

        return user

async def update_user_status(
        user_id: int,
        is_active: bool
):
    """Flip a user's active flag.

    token_gen is bumped on deactivation, which must revoke the sessions that
    exist right now, but not on reactivation: there is nothing to revoke yet,
    and bumping would only invalidate tokens minted after the flag went back.
    """
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
            """
            UPDATE tdac.users
            SET
                is_active = $2,
                token_gen = token_gen + CASE WHEN $2 = FALSE THEN 1 ELSE 0 END
            WHERE id = $1
            RETURNING
                id,
                username,
                role_id,
                is_active,
                created_at
            """,
            user_id,
            is_active
        )

        return user

async def delete_user(user_id: int):
    async with database.pool.acquire() as connection:
        user = await connection.fetchrow(
             """
            DELETE FROM tdac.users
            WHERE id = $1
            RETURNING
                id,
                username
            """,
            user_id
        )

        return user