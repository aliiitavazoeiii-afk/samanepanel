#!/usr/bin/env bash
# No build / no pip. Hotpatch only the running sister DigiKala and Django containers.
set -Eeuo pipefail
APP=/opt/dia-darma-fresh
test "$(id -u)" -eq 0
cd "$APP"
test "$(git branch --show-current)" = dia-darma-fresh
git diff --quiet && git diff --cached --quiet || { echo "STOP: Git working tree dirty"; exit 1; }
git fetch origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh

SALES_CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
WEB_CID="$(docker compose -f compose.fresh.yml ps -q web)"
test -n "$SALES_CID" && test -n "$WEB_CID"
test "$(docker inspect -f '{{.State.Running}}' "$SALES_CID")" = true
test "$(docker inspect -f '{{.State.Running}}' "$WEB_CID")" = true
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import fastapi,uvicorn,multipart; print("SISTER_RUNTIME_OK")'
docker compose -f compose.fresh.yml exec -T web python -c 'import django,psycopg; print("DJANGO_RUNTIME_OK")'

umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="$APP/backups/dk-catalog-actions-$STAMP"
mkdir -p "$BACKUP/sales" "$BACKUP/web"

echo "Backup of running sister SQLite before any changes"
docker compose -f compose.fresh.yml exec -T sister-digikala python -c \
  'import sqlite3,sys; x=sqlite3.connect("/data/sales.sqlite3"); y=sqlite3.connect("/data/"+sys.argv[1]); x.backup(y); y.close(); x.close()' \
  "before-dk-admin-$STAMP.sqlite3"
docker cp "$SALES_CID:/data/before-dk-admin-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"

FILES="dk_catalog_preferences.py master_api.py master_v2_api.py master_v2_logic.py digikala_auto_link.py digikala_manual_pack.py"
for file in $FILES; do
  test -f "$APP/daily_sales_service/$file"
  if docker cp "$SALES_CID:/app/daily_sales_service/$file" "$BACKUP/sales/$file" 2>/dev/null; then
    echo "ORIGINAL_BACKED_UP=$file"
  fi
done
docker cp "$WEB_CID:/app/core/sister_sales.py" "$BACKUP/web/sister_sales.py"

PATCH_STARTED=0
rollback() {
  rc=$?
  trap - ERR INT TERM
  if [ "$PATCH_STARTED" = 1 ]; then
    echo "ERROR: reverting modified sister Python sources..." >&2
    for file in $FILES; do
      if [ -f "$BACKUP/sales/$file" ]; then
        docker cp "$BACKUP/sales/$file" "$SALES_CID:/app/daily_sales_service/$file" || true
      else
        docker exec "$SALES_CID" rm -f "/app/daily_sales_service/$file" || true
      fi
    done
    docker cp "$BACKUP/web/sister_sales.py" "$WEB_CID:/app/core/sister_sales.py" || true
    docker compose -f compose.fresh.yml restart sister-digikala web || true
  fi
  echo "BACKUP=$BACKUP" >&2
  exit "$rc"
}
trap rollback ERR INT TERM

PATCH_STARTED=1
for file in $FILES; do
  docker cp "$APP/daily_sales_service/$file" "$SALES_CID:/app/daily_sales_service/$file"
done
docker cp "$APP/core/sister_sales.py" "$WEB_CID:/app/core/sister_sales.py"
docker compose -f compose.fresh.yml exec -T sister-digikala python -m compileall -q /app/daily_sales_service
docker compose -f compose.fresh.yml exec -T web python -m compileall -q /app/core/sister_sales.py
docker compose -f compose.fresh.yml restart sister-digikala web

echo "Read-only HTTP smoke of the live catalog, including removed tab"
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,os,sqlite3,time,urllib.request
pwd=os.environ["SALES_ADMIN_PASSWORD"]
user=os.environ.get("SALES_ADMIN_USER","bridge")
auth=base64.b64encode((user+":"+pwd).encode()).decode()
last=None
for attempt in range(25):
    try:
        for status in ("unmapped","removed"):
            req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/catalog?status="+status,
                                        headers={"Authorization":"Basic "+auth})
            with urllib.request.urlopen(req,timeout=4) as response:
                assert response.status==200
                body=response.read().decode()
            assert "حذف‌شده‌ها" in body
            if status=="unmapped":
                assert "/daily-sales/catalog/edit" in body
                assert "/daily-sales/catalog/archive" in body
        break
    except Exception as exc:
        last=exc
        time.sleep(2)
else:
    raise RuntimeError("Catalog HTTP check failed: "+str(last))
db=sqlite3.connect(os.environ.get("SALES_DB_PATH","/data/sales.sqlite3"))
try:
    assert db.execute("SELECT COUNT(*) FROM products").fetchone()[0]==538
    db.execute("SELECT COUNT(*) FROM dk_catalog_preferences").fetchone()
finally: db.close()
print("SISTER_DIGIKALA_CATALOG_EDIT_REMOVE_RESTORE_HTTP_OK")
print("SOURCE_538_VARIANTS_PRESERVED")
PY
code="$(curl -sS --max-time 6 -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/settings/products/platforms/digikala/)"
test "$code" = 302 || test "$code" = 200

trap - ERR INT TERM
echo "SISTER_DIGIKALA_SINGLE_ITEM_EDIT_DELETE_RESTORE_READY"
echo "BACKUP_PATH=$BACKUP"
echo "NOTE: hotpatched running containers; future RECREATE must rebuild from current GitHub source."
