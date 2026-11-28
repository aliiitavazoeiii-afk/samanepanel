#!/usr/bin/env bash
# Offline UI-only update: destination received by ME or MEHR, not a named bank.
set -Eeuo pipefail
cd /opt/dia-darma-fresh
test "$(id -u)" = "0" || { echo "STOP: root required"; exit 1; }
test "$(git branch --show-current)" = "dia-darma-fresh" || { echo "STOP: wrong branch"; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "STOP: local modifications"; exit 1; }
docker compose -f compose.fresh.yml config --quiet
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
test -n "$CID"
test "$(docker inspect -f '{{.State.Running}}' "$CID")" = "true"
case "$(docker inspect -f '{{.Name}}' "$CID")" in *dia-darma-fresh*) ;; *) echo "STOP: incorrect container"; exit 1 ;; esac

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="/opt/dia-darma-fresh/backups/customer-destination-only-$STAMP"
mkdir -p "$BACKUP/daily_sales_service"
echo "=== Backup SQLite and current running UI ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - "$STAMP" <<'PY'
import os,sqlite3,sys
p=os.getenv("SALES_DB_PATH","/data/sales.sqlite3")
src=sqlite3.connect("file:"+p+"?mode=ro",uri=True)
dst=sqlite3.connect("/data/customer-dest-"+sys.argv[1]+".sqlite3")
try:src.backup(dst)
finally:dst.close();src.close()
PY
docker cp "$CID:/data/customer-dest-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
for f in sister_invoice_api.py sister_finance_api.py; do
  docker cp "$CID:/app/daily_sales_service/$f" "$BACKUP/daily_sales_service/$f"
done
for f in daily_sales_service/sister_invoice_api.py daily_sales_service/sister_finance_api.py tests/test_bankfree_customer_ui_v1.py; do
  test -s "$f"
  docker cp "$f" "$CID:/tmp/$(basename "$f")"
  docker exec "$CID" python -m py_compile "/tmp/$(basename "$f")"
done
echo "BACKUP_READY=$BACKUP"

CHANGED=0
rollback(){
  rc=$?
  trap - ERR INT TERM
  if [ "$CHANGED" = 1 ]; then
    for f in sister_invoice_api.py sister_finance_api.py; do
      docker cp "$BACKUP/daily_sales_service/$f" "$CID:/app/daily_sales_service/$f" || true
    done
    docker exec "$CID" rm -f /app/tests/test_bankfree_customer_ui_v1.py || true
    docker compose -f compose.fresh.yml restart sister-digikala || true
  fi
  echo "CUSTOMER_DESTINATION_PATCH_FAILED BACKUP=$BACKUP"
  exit "$rc"
}
trap rollback ERR INT TERM
CHANGED=1
for f in daily_sales_service/sister_invoice_api.py daily_sales_service/sister_finance_api.py tests/test_bankfree_customer_ui_v1.py; do
  docker cp "$f" "$CID:/app/$f"
done

echo "=== Run isolated tests; no live transactions ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python -m unittest discover -s tests -p test_bankfree_customer_ui_v1.py -v
echo "=== Restart only isolated sister sales service ==="
docker compose -f compose.fresh.yml restart sister-digikala
echo "=== Check live page HTML (GET only) ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,os,time,urllib.request
creds=os.getenv("SALES_ADMIN_USER","admin")+":"+os.environ["SALES_ADMIN_PASSWORD"]
auth="Basic "+base64.b64encode(creds.encode()).decode()
for route,needle in (("invoices/new","name=\"destination\""),("invoices/mehr","طلب من از مهر به تفکیک فاکتور"),("finance","فروش ثبت‌شده"),("finance/accounts","دریافت به من یا مهر")):
    for attempt in range(12):
        try:
            req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/"+route,headers={"Authorization":auth})
            with urllib.request.urlopen(req,timeout=10) as response:
                content=response.read().decode()
                assert response.status==200 and needle in content
                assert 'name="account_id"' not in content
            print("BANK_FREE_PAGE_OK",route)
            break
        except Exception:
            if attempt==11:raise
            time.sleep(2)
PY
trap - ERR INT TERM
echo "CUSTOMER_DESTINATION_ONLY_DEPLOYED_OK"
echo "BACKUP=$BACKUP"
echo "NOTE: existing bank ledger history preserved; hotpatch requires later image rebuild."
