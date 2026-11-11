#!/usr/bin/env bash
# Sister-only no-build synchronized-code catalog upgrade; no Docker image, volume or pip changes.
set -Eeuo pipefail
APP=/opt/dia-darma-fresh
cd "$APP"
test "$(id -u)" = 0
test "$(git branch --show-current)" = dia-darma-fresh
git diff --quiet && git diff --cached --quiet || { echo "STOP: uncommitted tracked source"; exit 1; }
git fetch --quiet origin dia-darma-fresh
git merge --ff-only origin/dia-darma-fresh
test -f daily_sales_service/dk_catalog_preferences.py
test -f daily_sales_service/master_api.py
test -f daily_sales_service/sister_finance_logic.py
test -f daily_sales_service/sister_finance_api.py
test -f core/sister_sales.py
test -f compose.fresh.yml
docker compose -f compose.fresh.yml config --quiet
SALES_CID="$(docker compose -f compose.fresh.yml ps -q sister-digikala)"
WEB_CID="$(docker compose -f compose.fresh.yml ps -q web)"
test -n "$SALES_CID" && test -n "$WEB_CID"
test "$(docker inspect -f '{{.State.Running}}' "$SALES_CID")" = true
test "$(docker inspect -f '{{.State.Running}}' "$WEB_CID")" = true
echo "=== PRECHECK LIVE SISTER ONLY ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import fastapi,uvicorn,multipart; print("SALES_RUNTIME_OK")'
docker compose -f compose.fresh.yml exec -T web python -c 'import django,psycopg; print("DJANGO_RUNTIME_OK")'
umask 077
STAMP="$(date +%Y%m%dT%H%M%S)"
BACKUP="$APP/backups/dk-catalog-actions-v3-$STAMP"
mkdir -p "$BACKUP"
OLD="/app/daily_sales_service.pre_dk_catalog_v3_$STAMP"
STAGE="/app/daily_sales_service.stage_dk_catalog_v3_$STAMP"
echo "=== BACKUP SISTER SQLITE AND BOTH SOURCE SNAPSHOTS ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3,sys; x=sqlite3.connect("/data/sales.sqlite3"); y=sqlite3.connect("/data/"+sys.argv[1]); x.backup(y); y.close(); x.close()' "before-catalog-v3-$STAMP.sqlite3"
docker cp "$SALES_CID:/data/before-catalog-v3-$STAMP.sqlite3" "$BACKUP/sister-sales.sqlite3"
test -s "$BACKUP/sister-sales.sqlite3"
docker cp "$SALES_CID:/app/daily_sales_service" "$BACKUP/daily_sales_service"
docker cp "$WEB_CID:/app/core/sister_sales.py" "$BACKUP/sister_sales.py"
test -f "$BACKUP/daily_sales_service/app.py" && test -f "$BACKUP/sister_sales.py"
echo "=== STAGE COMPLETE, MATCHING SISTER MODULE SOURCE ==="
docker cp "$APP/daily_sales_service" "$SALES_CID:$STAGE"
docker compose -f compose.fresh.yml exec -T sister-digikala python -m compileall -q "$STAGE"
SWAP_STARTED=0
rollback() {
  local rc=$?
  trap - ERR INT TERM
  echo "ERROR: sister upgrade failed at shell line ${BASH_LINENO[0]} (exit $rc)" >&2
  echo "=== SALES LOGS (LAST 50) ===" >&2
  docker logs --tail 50 "$SALES_CID" >&2 || true
  echo "=== DJANGO LOGS (LAST 30) ===" >&2
  docker logs --tail 30 "$WEB_CID" >&2 || true
  if [ "$SWAP_STARTED" = 1 ]; then
    echo "=== RESTORING PREVIOUS SISTER SOURCE ===" >&2
    if docker exec "$SALES_CID" test -d "$OLD" 2>/dev/null; then
      docker exec "$SALES_CID" sh -c 'rm -rf /app/daily_sales_service' || true
      docker exec "$SALES_CID" mv "$OLD" /app/daily_sales_service || true
    else
      docker cp "$BACKUP/daily_sales_service/." "$SALES_CID:/app/daily_sales_service/" || true
    fi
  fi
  docker cp "$BACKUP/sister_sales.py" "$WEB_CID:/app/core/sister_sales.py" || true
  docker compose -f compose.fresh.yml restart sister-digikala web || true
  echo "ROLLBACK_CODE_SNAPSHOT=$BACKUP" >&2
  exit "$rc"
}
trap rollback ERR INT TERM
SWAP_STARTED=1
docker exec "$SALES_CID" mv /app/daily_sales_service "$OLD"
docker exec "$SALES_CID" mv "$STAGE" /app/daily_sales_service
docker cp "$APP/core/sister_sales.py" "$WEB_CID:/app/core/sister_sales.py"
echo "=== PREFLIGHT NEW CODE BEFORE RESTART (FASTAPI 0.137+ SAFE) ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import fastapi
from daily_sales_service.app import app
from daily_sales_service.master_v2_api import router
required={"/daily-sales/catalog/"+name for name in ("edit","archive","restore")}
nested={r.path for r in router.routes if hasattr(r,"path")}
assert required<=nested, ("Nested paths missing",required-nested)
paths=app.openapi()["paths"]
for path in required:
    assert "post" in paths.get(path,{}), ("OpenAPI missing POST",path)
print("FASTAPI_VERSION",fastapi.__version__)
print("CATALOG_POST_ENDPOINTS_OPENAPI_PASS",sorted(required))
PY
BEFORE_COUNT="$(docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3,os; p=os.getenv("SALES_DB_PATH","/data/sales.sqlite3"); c=sqlite3.connect(p); print(c.execute("SELECT COUNT(*) FROM products").fetchone()[0]); c.close()')"
echo "PRODUCTS_BEFORE_RESTART=$BEFORE_COUNT"
echo "=== RESTART ONLY 2 SISTER CONTAINERS, NOT RECREATE ==="
docker compose -f compose.fresh.yml restart sister-digikala web
echo "=== VERIFY LIVE ROUTES AND READ-ONLY CATALOG ==="
docker compose -f compose.fresh.yml exec -T sister-digikala python - <<'PY'
import base64,os,sqlite3,time,urllib.request
from daily_sales_service.app import app
required={"/daily-sales/catalog/"+suffix for suffix in ("edit","archive","restore")}
paths=app.openapi()["paths"]
assert all("post" in paths.get(p,{}) for p in required), "Catalog POST missing from OpenAPI"
print("LIVE_ROUTES_VERIFIED_BY_OPENAPI",sorted(required),flush=True)
auth=base64.b64encode((os.getenv("SALES_ADMIN_USER","bridge")+":"+os.environ["SALES_ADMIN_PASSWORD"]).encode()).decode()
for state in ("unmapped","removed"):
    last=None
    for _ in range(15):
        try:
            req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/catalog?status="+state, headers={"Authorization":"Basic "+auth})
            with urllib.request.urlopen(req,timeout=5) as response:
                body=response.read().decode()
                assert response.status==200
            assert "حذف‌شده‌ها" in body
            if state=="unmapped":
                assert "/daily-sales/catalog/edit" in body
                assert "/daily-sales/catalog/archive" in body
            print("CATALOG_HTTP_OK",state,flush=True)
            break
        except Exception as exc:
            last=exc
            time.sleep(1)
    else:
        raise RuntimeError("HTTP check state="+state+" : "+repr(last))
c=sqlite3.connect(os.getenv("SALES_DB_PATH","/data/sales.sqlite3"))
try:
    n=c.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    print("SISTER_SOURCE_PRODUCT_COUNT",n,flush=True)
    assert n>0, "Empty source product catalog"
    c.execute("SELECT COUNT(*) FROM dk_catalog_preferences").fetchone()
finally: c.close()
print("=== REAL HTTP POST OPERATIONS, INVALID ID => NO DATA MODIFICATION ===")
from urllib.parse import urlencode
for op in ("edit","archive","restore"):
    fields={"variant_id":"-999999","page_no":"1"}
    if op=="edit": fields["display_title"]="Diagnostic"
    req=urllib.request.Request("http://127.0.0.1:8018/daily-sales/catalog/"+op,
        data=urlencode(fields).encode(),
        headers={"Authorization":"Basic "+auth,
                 "Content-Type":"application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=5) as response:
        html=response.read().decode()
        assert response.status==200, (op,response.status)
    assert "خطای عملیات" in html, (op,"Unexpected response")
    print("CATALOG_REAL_POST_REACHED",op,flush=True)
print("SISTER_DIGIKALA_CATALOG_EDIT_REMOVE_RESTORE_HTTP_OK")
PY
AFTER_COUNT="$(docker compose -f compose.fresh.yml exec -T sister-digikala python -c 'import sqlite3,os; p=os.getenv("SALES_DB_PATH","/data/sales.sqlite3"); c=sqlite3.connect(p); print(c.execute("SELECT COUNT(*) FROM products").fetchone()[0]); c.close()')"
test "$AFTER_COUNT" = "$BEFORE_COUNT"
echo "SISTER_VARIANT_COUNT_UNCHANGED=$AFTER_COUNT"
echo "=== VERIFY DJANGO AUTHENTICATED PROXY CODE ==="
docker compose -f compose.fresh.yml exec -T web python -c 'from core import sister_sales; expected={"catalog/"+s for s in ("edit","archive","restore")}; assert expected<=sister_sales._ALLOWED; assert expected<=sister_sales._POST; print("DJANGO_CATALOG_PROXY_ROUTES_OK")'
trap - ERR INT TERM
echo "SISTER_DIGIKALA_SINGLE_ITEM_EDIT_DELETE_RESTORE_READY"
echo "BACKUP_PATH=$BACKUP"
echo "NOTE: Source is hotpatched in the current running sister containers; recreates require updated images."
