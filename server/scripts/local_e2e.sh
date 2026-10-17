#!/bin/sh
# Local end-to-end proof against a real Postgres.
# Runs against the single real database ags42_data (DB_NAME in server/.env).
# The lab tables start empty, so the e2e rows are easy to spot and delete.
# Assumes uvicorn is already running on :8000 (background terminal task).
cd "$(dirname "$0")/.." || exit 1
mkdir -p work

echo "== root + db probe =="
curl -s http://127.0.0.1:8000/
echo
curl -s http://127.0.0.1:8000/api/testdb
echo

echo "== create admin =="
python3 - <<'PYEOF'
import asyncio
from app import database
from app.auth.security import hash_password

async def main():
    await database.connect_to_database()
    try:
        async with database.pool.acquire() as c:
            await c.execute(
                """INSERT INTO tdac.roles (id, name) VALUES (1,'admin'),(2,'engineer'),(10,'client')
                   ON CONFLICT (id) DO NOTHING""",
            )
            await c.execute(
                """INSERT INTO tdac.users (username, hashed_password, role_id, is_active)
                   VALUES ($1, $2, 1, TRUE)
                   ON CONFLICT (username) DO UPDATE SET hashed_password = EXCLUDED.hashed_password""",
                "gkadmin", hash_password("gkpass123"),
            )
            print("admin user ready: gkadmin")
    finally:
        await database.close_database()

asyncio.run(main())
PYEOF

echo "== login =="
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"gkadmin","password":"gkpass123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
echo "token received: $(echo "$TOKEN" | cut -c 1-24)..."

echo "== excel parse (real file) =="
curl -s -X POST http://127.0.0.1:8000/api/excel/workbook \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@$HOME/storage/downloads/Input_sheet_V8_AGS_mapped.xlsx" \
  > work/parsed.json
python3 -c "
import json
b = json.load(open('work/parsed.json'))
print('suggestions:', b['suggestions']['project_name'], '|', b['suggestions']['borehole_id'], '|', b['suggestions']['final_depth'])
print('rows: borelog', len(b['workbook']['borelog']), '/ spt', len(b['workbook']['spt']))
"

echo "== excel commit -> creates project 901 + BH 2 + all rows =="
python3 - "$TOKEN" <<'PYEOF'
import json, sys, urllib.request

token = sys.argv[1]
wb = json.load(open("work/parsed.json"))["workbook"]
body = json.dumps({
    "project_id": "901",
    "project_name": "Imported From Real File",
    "borehole_type": "BH",
    "workbook": wb,
}).encode()

req = urllib.request.Request(
    "http://127.0.0.1:8000/api/excel/projects",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as r:
    print(r.status, json.loads(r.read()))
PYEOF

echo "== verify rows landed in real Postgres =="
psql -h 127.0.0.1 -U postgres -d ags42_data \
  -c 'SELECT "PROJ_ID", "PROJ_NAME" FROM "ags42"."PROJ" WHERE "PROJ_ID" = $$901$$' \
  -c 'SELECT "LOCA_ID", "LOCA_FDEP" FROM "ags42"."LOCA"' \
  -c 'SELECT COUNT(*) AS geol_rows FROM "ags42"."GEOL"' \
  -c 'SELECT COUNT(*) AS spt_rows FROM "ags42"."ISPT"' \
  -c 'SELECT COUNT(*) AS core_rows FROM "ags42"."CORE"'

echo "== app reads it back through its own API =="
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8000/api/portfolio/summary | python3 -m json.tool | head -12
curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:8000/api/portfolio/projects/901/locas" | python3 -m json.tool | head -14
