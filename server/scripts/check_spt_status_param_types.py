"""Proof that the SPT status INSERT is accepted by a real PostgreSQL.

The unit suite runs against FakePool, which records calls without ever
handing the statement to the database. That is the blind spot that let the
broken CASE-on-a-shared-parameter INSERT ship: the Python values were right,
so every mock assertion passed, while PostgreSQL rejected the statement at
prepare time with AmbiguousParameterError.

This script connects for real and PREPAREs both variants of the INSERT so the
parameter-type inference actually runs. It writes nothing: everything happens
inside a transaction that is rolled back.

Run:  python3 scripts/check_spt_status_param_types.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import asyncpg

DSN = os.environ.get(
    "TDAC_PG_DSN",
    "postgresql://postgres@/ags42_data?host=/data/data/com.termux/files/usr/tmp",
)

# The variant that shipped and 500'd: $7 used twice, once as a column value
# and once inside an untyped CASE.
BROKEN = """
INSERT INTO "tdac"."SPT_RECORD_STATUS"
    ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
     "STATUS", "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
VALUES ($1, $2, $3, $4, $5, $6, $7,
        CASE WHEN $7 IS NULL THEN NULL ELSE now() END)
"""

# The shipped fix: every value bound exactly once.
FIXED = """
INSERT INTO "tdac"."SPT_RECORD_STATUS"
    ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
     "STATUS", "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""


async def main() -> int:
    conn = await asyncpg.connect(DSN)
    failures = 0

    # Both variants must be attempted against the real table definition.
    for label, sql, params in (
        (
            "BROKEN (shared $7 in a CASE)",
            BROKEN,
            ["P", "L", 1.5, "SPT-1", "APPROVED", 1, 1],
        ),
        (
            "FIXED (one bind parameter per column)",
            FIXED,
            ["P", "L", 1.5, "SPT-1", "APPROVED", 1, 1, None],
        ),
    ):
        tx = conn.transaction()
        await tx.start()
        try:
            await conn.execute(sql, *params)
        except asyncpg.PostgresError as exc:
            # Expected for the broken variant; a failure here is the proof.
            print(f"REJECTED  {label}")
            print(f"          {type(exc).__name__}: {exc}")
        else:
            print(f"ACCEPTED  {label}")
        finally:
            await tx.rollback()

    # Confirm the real thing works end to end, then roll it back.
    tx = conn.transaction()
    await tx.start()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO "tdac"."SPT_RECORD_STATUS"
                ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
                 "STATUS", "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING "STATUS", "APPROVED_BY", "APPROVED_AT"
            """,
            "P", "L", 2.5, "SPT-2", "APPROVED", 1, 1,
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        )
        print(f"ROW OK    {dict(row)}")
    except asyncpg.PostgresError as exc:
        failures += 1
        print(f"ROW FAILED {type(exc).__name__}: {exc}")
    finally:
        await tx.rollback()

    # A NULL approver pair must satisfy the CHECK on STATUS too.
    tx = conn.transaction()
    await tx.start()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO "tdac"."SPT_RECORD_STATUS"
                ("PROJ_ID", "LOCA_ID", "DEPTH_FROM", "SAMPLE_ID",
                 "STATUS", "CREATED_BY", "APPROVED_BY", "APPROVED_AT")
            VALUES ($1, $2, $3, $4, $5, $6, NULL, NULL)
            RETURNING "STATUS"
            """,
            "P", "L", 3.5, "SPT-3", "PENDING", 1,
        )
        print(f"NULL PAIR {dict(row)}")
    except asyncpg.PostgresError as exc:
        failures += 1
        print(f"NULL PAIR FAILED {type(exc).__name__}: {exc}")
    finally:
        await tx.rollback()

    await conn.close()
    print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
