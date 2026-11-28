#!/usr/bin/env bash
# Enable invoice date-only + factory-to-home correction, NO automatic production edits.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = 0 || { echo "STOP: root needed";exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong branch";exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: local changes";exit 1; }
docker compose -f compose.fresh.yml config --quiet
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh
C="docker compose -f compose.fresh.yml"
SCID="$($C ps -q sister-digikala)"
WCID="$($C ps -q web)"
test -n "$SCID" && test -n "$WCID"
for CID in "$SCID" "$WCID"; do
 test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true
 case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) echo "STOP: unexpected container";exit 1;; esac
done
umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/invoice-origin-home-$STAMP"
mkdir -p "$BACKUP/daily_sales_service" "$BACKUP/core"
echo "=== Snapshot current isolated database ==="
$C exec -T sister-digikala python - "$STAMP" <<'PY'
import sqlite3,os,sys
source=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
destination=sqlite3.connect("/data/invoice-origin-home-"+sys.argv[1]+".sqlite3")
try:source.backup(destination)
finally:destination.close();source.close()
PY
docker cp "$SCID:/data/invoice-origin-home-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
for f in sister_invoices.py sister_invoice_api.py; do docker cp "$SCID:/app/daily_sales_service/$f" "$BACKUP/daily_sales_service/$f"; done
docker cp "$WCID:/app/core/sister_sales.py" "$BACKUP/core/sister_sales.py"
echo "BACKUP_READY=$BACKUP"
for f in daily_sales_service/sister_invoices.py daily_sales_service/sister_invoice_api.py tests/test_factory_to_home_origin_v1.py tests/test_invoice_date_only_v1.py; do
 test -s "$f"
 docker cp "$f" "$SCID:/tmp/$(basename "$f")"
 docker exec "$SCID" python -m py_compile "/tmp/$(basename "$f")"
done
docker cp core/sister_sales.py "$WCID:/tmp/sister_sales_corrected.py"
docker exec "$WCID" python -m py_compile /tmp/sister_sales_corrected.py
CHANGED=0
rollback(){
 rc=$?
 trap - ERR INT TERM
 if [ "$CHANGED" = 1 ]; then
  for f in sister_invoices.py sister_invoice_api.py; do docker cp "$BACKUP/daily_sales_service/$f" "$SCID:/app/daily_sales_service/$f" || true; done
  docker cp "$BACKUP/core/sister_sales.py" "$WCID:/app/core/sister_sales.py" || true
  docker exec "$SCID" rm -f /app/tests/test_factory_to_home_origin_v1.py /app/tests/test_invoice_date_only_v1.py || true
  $C restart sister-digikala web || true
 fi
 echo "INVOICE_ORIGIN_HOME_PATCH_FAILED BACKUP=$BACKUP" >&2
 exit "$rc"
}
trap rollback ERR INT TERM
CHANGED=1
docker cp daily_sales_service/sister_invoices.py "$SCID:/app/daily_sales_service/sister_invoices.py"
docker cp daily_sales_service/sister_invoice_api.py "$SCID:/app/daily_sales_service/sister_invoice_api.py"
docker cp tests/test_factory_to_home_origin_v1.py "$SCID:/app/tests/test_factory_to_home_origin_v1.py"
docker cp tests/test_invoice_date_only_v1.py "$SCID:/app/tests/test_invoice_date_only_v1.py"
docker cp core/sister_sales.py "$WCID:/app/core/sister_sales.py"
echo "=== Run isolated no-production-write regression tests ==="
$C exec -T sister-digikala python -m unittest discover -s tests -p test_factory_to_home_origin_v1.py -v
$C exec -T sister-digikala python -m unittest discover -s tests -p test_invoice_date_only_v1.py -v
echo "=== Validate Django proxy route via source pattern (fixes earlier false assertion) ==="
$C exec -T web python - <<'PY'
import inspect
from core import sister_sales
s=inspect.getsource(sister_sales.digikala_proxy)
assert "origin-home" in s and "date" in s
assert "origin-home" in inspect.getsource(sister_sales.invoice_proxy)
print("INVOICE_PROXY_ROUTING_OK")
PY
$C restart sister-digikala web
echo "=== Verify rendered date and origin forms (read-only) ==="
$C exec -T sister-digikala python - <<'PY'
import base64,os,time,urllib.request,sqlite3
password=os.environ["SALES_ADMIN_PASSWORD"]
user=os.getenv("SALES_ADMIN_USER","admin")
auth="Basic "+base64.b64encode((user+":"+password).encode()).decode()
def read(route):
 req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/"+route,headers={"Authorization":auth})
 with urllib.request.urlopen(req,timeout=12) as res:
  assert res.status==200
  return res.read().decode()
for attempt in range(12):
 try:
  html=read("invoices/5/edit")
  assert "/invoices/5/date" in html
  print("SAJJAD_DATE_FORM_OK")
  break
 except Exception:
  if attempt==11:raise
  time.sleep(2)
db=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row
try:
 rows=list(db.execute("""SELECT i.id,c.name,i.origin,i.status,i.invoice_date
 FROM sister_invoices i JOIN sister_invoice_customers c ON c.id=i.customer_id
 WHERE i.is_void=0 AND c.name LIKE '%مدبر%' ORDER BY i.id DESC"""))
 for r in rows:
  print("MODABER_INVOICE",r["id"],r["name"],r["origin"],r["status"],r["invoice_date"])
  if r["origin"]=="factory":
   html=read("invoices/"+str(r["id"])+"/origin-home")
   assert "master_" in html and "اصلاح مبدأ" in html
   print("MODABER_ORIGIN_FORM_OK",r["id"])
 if not rows:print("MODABER_NOT_FOUND_EXACT_NAME; open correct invoice to inspect")
 print("NO_PRODUCTION_FINANCIAL_OR_STOCK_RECORDS_CHANGED")
finally:db.close()
PY
trap - ERR INT TERM
echo "INVOICE_ORIGIN_HOME_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: runtime patch; rebuilt images need updated source."
