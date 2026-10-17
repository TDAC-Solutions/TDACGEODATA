from contextlib import asynccontextmanager
import os

import app.database as database
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware

from app.database import (
    connect_to_database, 
    close_database,
    pool,
    )

from app.attachments.sharepoint_client import sharepoint
from app.auth.dependencies import get_current_admin
from app.auth.security import hash_password
from app.schemas.project import ProjectCreate
# Router
from app.auth.router import router as auth_router
from app.portfolio_router import router as portfolio_router
from app.field_data_router import router as field_data_router
from app.field_audit_router import router as field_audit_router
from app.spreadsheet_import.router import router as excel_router
from app.attachments.router import router as attachments_router
from app.borelog_report.router import router as borelog_report_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Connecting to database...")
    try:
        await database.connect_to_database()
    except RuntimeError as error:
        # The hint is the actionable part; uvicorn would otherwise bury it
        # under a traceback that never mentions how to fix it.
        print("ERROR: " + str(error), file=sys.stderr)
        raise
    print("Database connected.")
    yield
    print("Closing database connection...")
    await database.close_database()
    # Release the pooled Graph connections. Without this a redeploy leaves
    # idle sockets open until the process is killed.
    await sharepoint.close_client()
    print("Database connection closed.")

app = FastAPI(lifespan=lifespan)
app.include_router(portfolio_router)
app.include_router(field_data_router)
app.include_router(field_audit_router)
app.include_router(auth_router)
app.include_router(excel_router)
app.include_router(attachments_router)
app.include_router(borelog_report_router)
# Origins allowed to call the API from a browser. Read from the
# environment so a deployment declares its own rather than editing source:
# a hardcoded localhost makes the app unusable behind any reverse proxy.
_CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ALLOW_ORIGINS", "http://localhost:5173"
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MediaSafeGZipMiddleware(GZipMiddleware):
    """Compress API responses, except media downloads.

    Attachment content is a streaming response, sometimes a 206 with
    Content-Range. Compressing it would change the transfer encoding while
    the range still refers to the original (uncompressed) bytes, breaking
    video seeking. JSON payloads are the ones worth compressing; the large
    historic-lab-data responses travel uncompressed otherwise.
    """

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path", "").endswith(
            "/content"
        ):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(MediaSafeGZipMiddleware, minimum_size=1000)

@app.get('/')
def root():
    return{
        "message":"Tdac api is running"
    }

@app.get('/api/testdb')
async def test_database(current_admin: dict = Depends(get_current_admin)):
    async with database.pool.acquire() as connection:
        result = await connection.fetchval(
            "SELECT NOW()"
        )

        return {
            "message":"Database connected",
            "time": result
        }

@app.get('/api/test-schemas')
async def test_schema(current_admin: dict = Depends(get_current_admin)):
    async with database.pool.acquire() as connection:
        schemas = await connection.fetch(
            """
            SELECT schema_name 
            FROM information_schema.schemata
            ORDER BY schema_name
            """
        )

    return {
        "schemas":[
            row["schema_name"]
            for row in schemas
        ]
    }

@app.get('/api/test-tables')
async def test_tables(current_admin: dict = Depends(get_current_admin)):
    async with database.pool.acquire() as connection:
        tables = await connection.fetch(
            """
            SELECT
                table_schema,
                table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
            """
        )
        print("TABLES FROM DATABASE")
        print(tables)

    return {
        "tables":[
            {
                "schema":row["table_schema"],
                "table":row["table_name"]
            }
            for row in tables
        ]        
    }

@app.get('/api/test-user')
async def test_user(current_admin: dict = Depends(get_current_admin)):
    async with database.pool.acquire() as connection:
        columns =  await connection.fetch(
            """
                SELECT 
                    column_name,
                    data_type,
                    is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'tdac'
                AND table_name = 'users'
                ORDER BY ordinal_position
            """
        )
    return {
        "columns":[
            {
                "name":row["column_name"],
                "type": row['data_type'],
                "nullable": row["is_nullable"]
            }
            for row in columns
        ]
    }

@app.get('/api/test-role')
async def get_role(current_admin: dict = Depends(get_current_admin)):
    async with database.pool.acquire() as connection:
        columns = await connection.fetch(
            """
                SELECT
                column_name,
                data_type,
                is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'tdac'
                AND table_name = 'roles'
                ORDER BY ordinal_position
            """
        )
    return {
        "columns":[
            {
                "name":row["column_name"],
                "type":row["data_type"],
                "nullable":row["is_nullable"]
            }
            for row in columns
        ]
    }

# Removed: GET /api/test-password. It returned a real bcrypt hash of a known
# password to any anonymous caller, which hands an attacker both the hash and
# the plaintext it corresponds to. It served no purpose: hash_password is
# exercised directly in the test suite.

# Removed: POST /api/projects.
#
# It wrote a PROJ row and nothing else: no metadata, no locations, no audit
# trail. /api/portfolio/projects writes all of them in one transaction, and
# the client calls only that one. Two endpoints with the same purpose, one
# of them incomplete, is a trap for whoever reaches for it next. Nothing
# calls this path: verified across the client and the test suite.
