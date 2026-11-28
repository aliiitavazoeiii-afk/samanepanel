#!/usr/bin/env bash
# Date-only correction enablement; no production invoice date is modified by deploy.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = "0" || { echo "STOP: root only"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong branch"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: local changes"; exit 1; }
docker compose -f compose.fresh.yml config --quiet
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

COMPOSE="docker compose -f compose.fresh.yml"
SCID="$($COMPOSE ps -q sister-digikala)"
WCID="$($COMPOSE ps -q web)"
test -n "$SCID" && test -n "$WCID"
for CID in "$SCID" "$WCID"; do
  test "$(docker inspect -f '{{.State.Running}}' "$CID")" = "true"
  case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) echo "STOP: unexpected container"; exit 1 ;; esac
done

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/invoice-date-only-$STAMP"
mkdir -p "$BACKUP/daily_sales_service" "$BACKUP/core"
$COMPOSE exec -T sister-digikala python - "$STAMP" <<'PY'
import sqlite3,os,sys
source=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
destination=sqlite3.connect("/data/invoice-date-only-"+sys.argv[1]+".sqlite3")
try:source.backup(destination)
finally:destination.close();source.close()
PY
docker cp "$SCID:/data/invoice-date-only-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
docker cp "$SCID:/app/daily_sales_service/sister_invoices.py" "$BACKUP/daily_sales_service/sister_invoices.py"
docker cp "$SCID:/app/daily_sales_service/sister_invoice_api.py" "$BACKUP/daily_sales_service/sister_invoice_api.py"
docker cp "$WCID:/app/core/sister_sales.py" "$BACKUP/core/sister_sales.py"
echo "BACKUP_READY=$BACKUP"

for f in daily_sales_service/sister_invoices.py daily_sales_service/sister_invoice_api.py tests/test_invoice_date_only_v1.py; do
 test -s "$f"
 docker cp "$f" "$SCID:/tmp/$(basename "$f")"
 docker exec "$SCID" python -m py_compile "/tmp/$(basename "$f")"
done
test -s core/sister_sales.py
docker cp core/sister_sales.py "$WCID:/tmp/sister_sales_date_only.py"
docker exec "$WCID" python -m py_compile /tmp/sister_sales_date_only.py

CHANGED=0
rollback(){
 local rc=$?
 trap - ERR INT TERM
 if [ "$CHANGED" = 1 ]; then
   docker cp "$BACKUP/daily_sales_service/sister_invoices.py" "$SCID:/app/daily_sales_service/sister_invoices.py" || true
   docker cp "$BACKUP/daily_sales_service/sister_invoice_api.py" "$SCID:/app/daily_sales_service/sister_invoice_api.py" || true
   docker cp "$BACKUP/core/sister_sales.py" "$WCID:/app/core/sister_sales.py" || true
   docker exec "$SCID" rm -f /app/tests/test_invoice_date_only_v1.py || true
   $COMPOSE restart sister-digikala web || true
 fi
 echo "INVOICE_DATE_ONLY_PATCH_FAILED BACKUP=$BACKUP"
 exit "$rc"
}
trap rollback ERR INT TERM
CHANGED=1
docker cp daily_sales_service/sister_invoices.py "$SCID:/app/daily_sales_service/sister_invoices.py"
docker cp daily_sales_service/sister_invoice_api.py "$SCID:/app/daily_sales_service/sister_invoice_api.py"
docker cp tests/test_invoice_date_only_v1.py "$SCID:/app/tests/test_invoice_date_only_v1.py"
docker cp core/sister_sales.py "$WCID:/app/core/sister_sales.py"

echo "=== Isolated tests, no production writes ==="
$COMPOSE exec -T sister-digikala python -m unittest discover -s tests -p test_invoice_date_only_v1.py -v
$COMPOSE exec -T web python - <<'PY'
from core import sister_sales
assert "date" in sister_sales.invoice_proxy.__code__.co_consts or "date" in str(sister_sales.invoice_proxy.__code__.co_consts)
assert "invoices/5/date" not in sister_sales._POST
import re
assert re.fullmatch(r"invoices/5/date", "invoices/5/date")
print("INVOICE_DATE_PROXY_IMPORT_OK")
PY
echo "=== Restart backend and authenticated Django proxy ==="
$COMPOSE restart sister-digikala web
echo "=== Verify live GET invoice edit #5 (no POST writes) ==="
$COMPOSE exec -T sister-digikala python - <<'PY'
import os,base64,urllib.request,time,sqlite3
password=os.environ["SALES_ADMIN_PASSWORD"]
username=os.getenv("SALES_ADMIN_USER","admin")
token=base64.b64encode((username+":"+password).encode()).decode()
for attempt in range(12):
 try:
  request=urllib.request.Request("http://127.0.0.1:8018/daily-sales/invoices/5/edit",headers={"Authorization":"Basic "+token})
  with urllib.request.urlopen(request,timeout=10) as r:
   page=r.read().decode()
   assert r.status==200 and "/invoices/5/date" in page and "فقط اصلاح تاریخ" in page
  print("DATE_EDIT_FORM_LIVE_OK")
  break
 except Exception:
  if attempt==11:raise
  time.sleep(2)
p=os.getenv("SALES_DB_PATH","/data/sales.sqlite3")
conn=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
try:
 row=conn.execute("SELECT id,invoice_date,version FROM sister_invoices WHERE id=5").fetchone()
 print("SAJJAD_DATE_CURRENT",row)
 print("NO_PRODUCTION_INVOICE_EDIT_WAS_MADE")
finally:conn.close()
PY
trap - ERR INT TERM
echo "INVOICE_DATE_ONLY_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "Note: rebuilt images must include source changes before future container recreation."
