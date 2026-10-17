#!/bin/sh
# Second-flow proof: field-data reads + Overview excel import behavior.
# The duplicate guard must refuse the same rows under a new borehole id,
# and accept a workbook whose rows are genuinely new.
cd "$(dirname "$0")/.." || exit 1

TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"gkadmin","password":"gkpass123"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

echo "== field-data: borehole records for 901 / BH 2 =="
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/portfolio/projects/901/locas/BH%202/field-data/borehole" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
recs = r['records']
print('records:', len(recs))
print('first:', recs[0])
print('last: ', recs[-1])
"

echo "== field-data: SPT records =="
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/portfolio/projects/901/locas/BH%202/field-data/spt" \
  | python3 -c "
import sys, json
r = json.load(sys.stdin)
print('records:', len(r['records']))
print('last:', r['records'][-1])
"

echo "== guard: same rows under a NEW borehole id must 409 =="
python3 - "$TOKEN" <<'PYEOF'
import json, sys, urllib.request, urllib.error

token = sys.argv[1]
wb = json.load(open("work/parsed.json"))["workbook"]

# Same rows, different borehole number: without the guard this would
# insert a second full copy of every layer, SPT and core row.
wb["project_info"]["borehole_number"] = "BH 9"

body = json.dumps({"borehole_type": "BH", "workbook": wb}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/excel/projects/901/locas",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req)
    print("ERROR: duplicate rows were accepted under a new borehole id")
    sys.exit(1)
except urllib.error.HTTPError as e:
    print(e.code, json.loads(e.read())["detail"])
PYEOF

echo "== guard: genuinely different rows ARE accepted =="
python3 - "$TOKEN" <<'PYEOF'
import json, sys, urllib.request
from decimal import Decimal

token = sys.argv[1]
wb = json.load(open("work/parsed.json"))["workbook"]

# Shift every depth so the rows are real new measurements, not a copy.
def shifted(sheet, depth_keys):
    for row in wb.get(sheet) or []:
        for key in depth_keys:
            if row.get(key) is not None:
                row[key] = float(Decimal(str(row[key])) + Decimal("100"))

shifted("borelog", ["depth_from", "depth_to"])
shifted("rock_profile", ["depth_from", "depth_to"])
shifted("spt", ["spt_depth"])
wb["project_info"]["borehole_number"] = "BH 9"
wb["project_info"]["final_depth"] = float(Decimal(str(wb["project_info"]["final_depth"])) + Decimal("100"))

body = json.dumps({"borehole_type": "BH", "workbook": wb}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/excel/projects/901/locas",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req) as r:
    print(r.status, json.loads(r.read()))
PYEOF

echo "== duplicate import of the SAME borehole must 409 =="
python3 - "$TOKEN" <<'PYEOF'
import json, sys, urllib.request, urllib.error

token = sys.argv[1]
wb = json.load(open("work/parsed.json"))["workbook"]
wb["project_info"]["borehole_number"] = "BH 9"

body = json.dumps({"borehole_type": "BH", "workbook": wb}).encode()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/excel/projects/901/locas",
    data=body,
    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    method="POST",
)
try:
    urllib.request.urlopen(req)
    print("ERROR: duplicate was accepted")
    sys.exit(1)
except urllib.error.HTTPError as e:
    print(e.code, json.loads(e.read())["detail"])
PYEOF

echo "== locas list now has both =="
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://127.0.0.1:8000/api/portfolio/projects/901/locas" \
  | python3 -c "import sys,json;print([l['loca_id'] for l in json.load(sys.stdin)['locas']])"
