#!/usr/bin/env bash
# Demo helper: log in as the municipal admin and corrupt ONE event on a load (hash is NOT recomputed).
#   usage: demo/corrupt.sh [LOAD_ID] [EVENT_ID]      e.g.  demo/corrupt.sh DL-1002 19
set -euo pipefail
API="${API:-http://localhost:8000}"
LOAD="${1:-DL-1002}"
EVENT="${2:-19}"

TOKEN=$(curl -sf -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin1","password":"demo123"}' | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

echo ">>> POST $API/admin/loads/$LOAD/corrupt-event/$EVENT"
curl -sf -X POST "$API/admin/loads/$LOAD/corrupt-event/$EVENT" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
echo
echo ">>> Now click 'Verify Chain' in the Municipal dashboard (or GET /loads/$LOAD/verify-integrity)."
