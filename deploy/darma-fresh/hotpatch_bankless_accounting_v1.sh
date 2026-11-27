#!/usr/bin/env bash
# Safe offline hotpatch for sister-only accounting. No external image pull.
# No recorded sales, stock, or platform claims are rewritten.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = 0 || { echo "STOP: run as root"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong repository branch"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: local uncommitted changes"; exit 1; }
docker compose -f compose.fresh.yml config --quiet
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

COMPOSE="docker compose -f compose.fresh.yml"
SCID="$($COMPOSE ps -q sister-digikala)"
WCID="$($COMPOSE ps -q web)"
test -n "$SCID" && test -n "$WCID" || { echo "STOP: missing containers"; exit 1; }
for CID in "$SCID" "$WCID"; do
  test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true || { echo "STOP: stopped container"; exit 1; }
  case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) echo "STOP: wrong application"; exit 1 ;; esac
done
for path in daily_sales_service/sister_finance_logic.py \
            daily_sales_service/sister_finance_api.py \
            daily_sales_service/sister_finance_bankless_v1.py \
            tests/test_bankless_platform_receipts_v1.py core/sister_sales.py; do
  test -s "$path" || { echo "STOP: missing $path"; exit 1; }
done

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/bankless-receipts-$STAMP"
mkdir -p "$BACKUP/daily_sales_service" "$BACKUP/core"
echo "=== Backup both isolated databases before code changes ==="
$COMPOSE exec -T sister-digikala python - "$STAMP" <<'PY'
import sqlite3,sys
stamp=sys.argv[1]
source=sqlite3.connect("file:/data/sales.sqlite3?mode=ro",uri=True)
destination=sqlite3.connect("/data/bankless-receipts-"+stamp+".sqlite3")
source.backup(destination)
destination.close()
source.close()
PY
docker cp "$SCID:/data/bankless-receipts-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
$COMPOSE exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP/django-postgres.sql"
test -s "$BACKUP/django-postgres.sql"

echo "=== Backup prior container code ==="
for path in daily_sales_service/sister_finance_logic.py daily_sales_service/sister_finance_api.py; do
  docker cp "$SCID:/app/$path" "$BACKUP/$path"
done
docker cp "$WCID:/app/core/sister_sales.py" "$BACKUP/core/sister_sales.py"
for path in daily_sales_service/sister_finance_logic.py daily_sales_service/sister_finance_api.py daily_sales_service/sister_finance_bankless_v1.py; do
  docker cp "$path" "$SCID:/tmp/$(basename "$path")"
  docker exec "$SCID" python -m py_compile "/tmp/$(basename "$path")"
done
docker cp core/sister_sales.py "$WCID:/tmp/sister_sales_bankless.py"
docker exec "$WCID" python -m py_compile /tmp/sister_sales_bankless.py
echo "BACKUP_READY=$BACKUP"

CHANGED=0
rollback() {
  rc=$?
  trap - ERR INT TERM
  echo "FAILED accounting hotpatch; restoring previous runtime code" >&2
  if [ "$CHANGED" -eq 1 ]; then
    docker cp "$BACKUP/daily_sales_service/sister_finance_logic.py" "$SCID:/app/daily_sales_service/sister_finance_logic.py" || true
    docker cp "$BACKUP/daily_sales_service/sister_finance_api.py" "$SCID:/app/daily_sales_service/sister_finance_api.py" || true
    docker cp "$BACKUP/core/sister_sales.py" "$WCID:/app/core/sister_sales.py" || true
    docker exec "$SCID" rm -f /app/daily_sales_service/sister_finance_bankless_v1.py /app/tests/test_bankless_platform_receipts_v1.py || true
    docker compose -f compose.fresh.yml restart sister-digikala web || true
  fi
  echo "SOURCE_BACKUP=$BACKUP" >&2
  echo "The newly created empty receipt table may remain; no existing entries are changed by rollback." >&2
  exit "$rc"
}
trap rollback ERR INT TERM

CHANGED=1
echo "=== Copy accounting logic and new receipt module ==="
for path in daily_sales_service/sister_finance_logic.py daily_sales_service/sister_finance_api.py daily_sales_service/sister_finance_bankless_v1.py; do
  docker cp "$path" "$SCID:/app/$path"
done
docker cp tests/test_bankless_platform_receipts_v1.py "$SCID:/app/tests/test_bankless_platform_receipts_v1.py"
docker cp core/sister_sales.py "$WCID:/app/core/sister_sales.py"

echo "=== Validate on temporary databases; no real sales posted ==="
$COMPOSE exec -T sister-digikala python -m unittest discover -s tests -p 'test_bankless_platform_receipts_v1.py' -v
$COMPOSE exec -T web python manage.py check
$COMPOSE exec -T web python - <<'PY'
from core import sister_sales
assert {"finance/receipts/add","finance/receipts/cancel"} <= sister_sales._ALLOWED
assert {"finance/receipts/add","finance/receipts/cancel"} <= sister_sales._POST
print("BANKLESS_DJANGO_PROXY_OK",flush=True)
PY

echo "=== Apply additive receipts-table schema (no sales, prices or stock edits) ==="
$COMPOSE exec -T sister-digikala python - <<'PY'
import os
from daily_sales_service.engine import dbconnect
from daily_sales_service.sister_finance_bankless_v1 import ensure_schema
path=os.environ.get("SALES_DB_PATH","/data/sales.sqlite3")
conn=dbconnect(path)
try:
    ensure_schema(conn)
    names={r[1] for r in conn.execute("PRAGMA table_info(sister_unallocated_receipts)")}
    assert {"party_id","amount_toman","request_key","cancelled_at"} <= names
    print("BANKLESS_RECEIPT_SCHEMA_OK",flush=True)
finally:
    conn.close()
PY

echo "=== Restart sister services only; no image build ==="
$COMPOSE restart sister-digikala web

echo "=== Verify authenticated live read-only finance and sales endpoints ==="
$COMPOSE exec -T sister-digikala python - <<'PY'
import base64,json,os,time,urllib.request
base="http://127.0.0.1:8018/daily-sales/"
creds=(os.environ["SALES_ADMIN_USER"]+":"+os.environ["SALES_ADMIN_PASSWORD"]).encode()
header={"Authorization":"Basic "+base64.b64encode(creds).decode()}
for route in ("finance/movements?section=receipt","finance/sales","api/sister-finance.json"):
    for attempt in range(12):
        try:
            req=urllib.request.Request(base+route,headers=header)
            with urllib.request.urlopen(req,timeout=10) as response:
                assert response.status==200
                body=response.read().decode()
            if route.startswith("finance/movements"):
                assert 'finance/receipts/add' in body
                assert 'name="account_id"' not in body
            if route=="finance/sales":
                assert "تفکیک فروش کسب‌وکارها" in body
            if route.startswith("api/"):
                data=json.loads(body)
                assert "platforms" in data and "sales" in data
            print("FINANCE_ROUTE_OK",route,flush=True)
            break
        except Exception:
            if attempt==11: raise
            time.sleep(2)
PY
trap - ERR INT TERM
echo "BANKLESS_ACCOUNTING_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: hotpatch survives container restart but not image-based recreation."
