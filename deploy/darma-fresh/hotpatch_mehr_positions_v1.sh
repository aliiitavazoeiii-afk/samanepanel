#!/usr/bin/env bash
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = 0
test "$(git branch --show-current)" = "dia-darma-fresh"
git diff --quiet && git diff --cached --quiet || { echo "STOP: local changes"; exit 1; }
docker compose -f compose.fresh.yml config --quiet
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
test -n "$CID" && test "$(docker inspect -f '{{.State.Running}}' "$CID")" = true
case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) exit 1 ;; esac
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/mehr-positions-$STAMP"
umask 077
mkdir -p "$BACKUP/daily_sales_service"
docker compose -f compose.fresh.yml exec -T sister-digikala python - "$STAMP" <<'PY'
import os,sqlite3,sys
src=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
dst=sqlite3.connect("/data/mehr-positions-"+sys.argv[1]+".sqlite3")
try:src.backup(dst)
finally:dst.close();src.close()
PY
docker cp "$CID:/data/mehr-positions-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
for f in sister_invoice_api.py sister_finance_api.py; do
  docker cp "$CID:/app/daily_sales_service/$f" "$BACKUP/daily_sales_service/$f"
done
echo "BACKUP_READY=$BACKUP"
FILES="daily_sales_service/sister_invoice_api.py daily_sales_service/sister_finance_api.py daily_sales_service/mehr_document_positions_v1.py tests/test_mehr_document_positions_v1.py"
for f in $FILES; do
  test -s "$f"
  docker cp "$f" "$CID:/tmp/$(basename "$f")"
  docker exec "$CID" python -m py_compile "/tmp/$(basename "$f")"
done
CHANGED=0
rollback(){
  rc=$?
  trap - ERR INT TERM
  if [ "$CHANGED" = 1 ]; then
    for f in sister_invoice_api.py sister_finance_api.py; do
      docker cp "$BACKUP/daily_sales_service/$f" "$CID:/app/daily_sales_service/$f" || true
    done
    docker exec "$CID" rm -f /app/daily_sales_service/mehr_document_positions_v1.py /app/tests/test_mehr_document_positions_v1.py || true
    docker compose -f compose.fresh.yml restart sister-digikala || true
  fi
  echo "MEHR_DISPLAY_PATCH_FAILED BACKUP=$BACKUP"
  exit "$rc"
}
trap rollback ERR INT TERM
CHANGED=1
for f in $FILES; do docker cp "$f" "$CID:/app/$f"; done
docker compose -f compose.fresh.yml exec -T sister-digikala python -m unittest discover -s tests -p test_mehr_document_positions_v1.py -v
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import os,sqlite3
from daily_sales_service.sister_invoices import mehr_balance,mehr_open_items
from daily_sales_service.mehr_document_positions_v1 import summarize_mehr_documents
db=sqlite3.connect("file:"+os.getenv("SALES_DB_PATH","/data/sales.sqlite3")+"?mode=ro",uri=True)
db.row_factory=sqlite3.Row
db.execute("PRAGMA query_only=ON")
try:
    v=summarize_mehr_documents(mehr_open_items(db),mehr_balance(db))
    for k in ("invoice_excess","invoice_due","purchases_due","ledger_net","net_claim","net_payable","unallocated_difference"):
        print("MEHR_CURRENT",k,v[k])
    for r in db.execute("SELECT id,amount,destination FROM sister_invoice_receipts WHERE invoice_id=2 ORDER BY id"):
        print("MODERNA_RECEIPT_CURRENT",r["id"],r["amount"],r["destination"])
    print("MEHR_READ_ONLY_RECONCILIATION_OK")
finally:db.close()
PY
docker compose -f compose.fresh.yml restart sister-digikala
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,os,time,urllib.request
user=os.getenv("SALES_ADMIN_USER","admin")
password=os.environ["SALES_ADMIN_PASSWORD"]
auth="Basic "+base64.b64encode((user+":"+password).encode()).decode()
for route,expected in (("invoices/mehr","طلب من از مهر به تفکیک فاکتور"),("finance","طلب من از مهر بابت فاکتورها")):
    for attempt in range(12):
        try:
            req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/"+route,headers={"Authorization":auth})
            with urllib.request.urlopen(req,timeout=10) as response:
                content=response.read().decode()
                assert response.status==200 and expected in content
            print("MEHR_DISPLAY_LIVE_OK",route)
            break
        except Exception:
            if attempt==11:raise
            time.sleep(2)
PY
trap - ERR INT TERM
echo "MEHR_POSITIONS_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: hotpatch is runtime only; future image rebuild required."
