#!/usr/bin/env bash
# Scoped Samanepanel invoice/UI rollout: back up before pulling; never import catalog.
set -euo pipefail
umask 077

APP=/opt/dia-darma-fresh
COMPOSE=compose.fresh.yml
test "$(id -u)" = 0 || { echo "ERROR: root required" >&2; exit 1; }
cd "$APP"
test -f .env && test -f "$COMPOSE" || { echo "ERROR: wrong project" >&2; exit 1; }
test "$(git branch --show-current)" = dia-darma-fresh || { echo "ERROR: wrong branch" >&2; exit 1; }
git diff --quiet && git diff --cached --quiet || { echo "ERROR: tracked local changes; stop" >&2; exit 1; }
docker compose -f "$COMPOSE" config --quiet
for service in db web sister-digikala; do
  docker compose -f "$COMPOSE" ps --status running --services | grep -qx "$service" ||
    { echo "ERROR: service not running: $service" >&2; exit 1; }
done

echo "PRE-INSTALL: source checkout is $(git rev-parse --short HEAD)"
STAMP="$(date +%Y%m%d-%H%M%S)"
mkdir -p backups
echo "Backing up production PostgreSQL BEFORE any git pull or service restart."
PG_BACKUP="backups/pre-invoice-$STAMP.postgres.sql"
docker compose -f "$COMPOSE" exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$PG_BACKUP"
test -s "$PG_BACKUP" || { echo "ERROR: PostgreSQL backup empty" >&2; exit 1; }
echo "Backing up production SQLite online using sqlite3 backup API."
SQLITE_COPY="/data/pre-invoice-$STAMP.sqlite3"
docker compose -f "$COMPOSE" exec -T sister-digikala python -c \
  'import sqlite3,sys; source=sqlite3.connect("/data/sales.sqlite3"); target=sqlite3.connect(sys.argv[1]); source.backup(target); target.close(); source.close()' "$SQLITE_COPY"
SALES_CID="$(docker compose -f "$COMPOSE" ps -q sister-digikala)"
docker cp "$SALES_CID:$SQLITE_COPY" "backups/pre-invoice-$STAMP.sqlite3"
test -s "backups/pre-invoice-$STAMP.sqlite3" || { echo "ERROR: SQLite backup empty" >&2; exit 1; }
docker compose -f "$COMPOSE" exec -T sister-digikala python -c \
  'import sqlite3,sys; p=sys.argv[1]; c=sqlite3.connect(p); assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"; c.close()' "$SQLITE_COPY"
docker compose -f "$COMPOSE" exec -T sister-digikala python -c \
  'import os,sys; os.remove(sys.argv[1])' "$SQLITE_COPY"
echo "BACKUPS_OK $PG_BACKUP and backups/pre-invoice-$STAMP.sqlite3"

# The running images themselves are retained as rollback tags. Do not copy
# the live database volumes into images; .dockerignore excludes .env/backups.
WEB_CID="$(docker compose -f "$COMPOSE" ps -q web)"
WEB_IMG="$(docker inspect --format '{{.Image}}' "$WEB_CID")"
SALES_IMG="$(docker inspect --format '{{.Image}}' "$SALES_CID")"
docker image inspect "$WEB_IMG" >/dev/null || { echo "ERROR: web base image missing; stop" >&2; exit 1; }
docker image inspect "$SALES_IMG" >/dev/null || { echo "ERROR: sales base image missing; stop" >&2; exit 1; }
docker image tag "$WEB_IMG" "dia-darma-fresh-web-preinvoice:$STAMP"
docker image tag "$SALES_IMG" "dia-darma-fresh-sister-preinvoice:$STAMP"
docker image tag "$WEB_IMG" dia-darma-fresh-web-offline-base:local
docker image tag "$SALES_IMG" dia-darma-fresh-sister-offline-base:local
echo "OLD_IMAGES_PRESERVED $STAMP"

echo "Fetching ONLY the approved dia-darma-fresh branch."
git fetch origin dia-darma-fresh
git pull --ff-only origin dia-darma-fresh
test -f daily_sales_service/sister_invoices.py
test -f daily_sales_service/sister_invoice_api.py
test -f static/core/jalali-global.js

echo "Offline builds; existing containers stay running throughout build/tests."
docker build --pull=false --network=none -f deploy/darma-fresh/Dockerfile.web.offline \
  -t dia-darma-fresh-web:latest .
docker build --pull=false --network=none -f deploy/darma-fresh/Dockerfile.sister-sales.offline \
  -t dia-darma-fresh-sister-digikala:latest .

echo "Django checks and proxy tests, no production migration in this phase."
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py check
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py test core.tests_sister_sales -v 2
echo "Compile all sister modules and run invoice and unified purchasing regressions in disposable containers."
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python sister-digikala \
  -m compileall -q daily_sales_service tests
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint env sister-digikala \
  -u SALES_START_EMPTY_STOCK python -m unittest discover -s tests -p 'test_sister_invoices.py' -v
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint env sister-digikala \
  -u SALES_START_EMPTY_STOCK python -m unittest discover -s tests -p 'test_sister_purchases.py' -v

echo "Verify expected invoice API routes before affecting running services."
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python sister-digikala - <<'PY'
from daily_sales_service.app import app
paths=app.openapi()["paths"]
root="/daily-sales"
for route in ("/purchases","/purchases/add","/purchases/payments/add",
              "/invoices","/invoices/new","/invoices/create",
              "/invoices/mehr","/invoices/mehr/settle",
              "/invoices/purchases","/invoices/purchases/add",
              "/invoices/{invoice_id}","/invoices/{invoice_id}/dispatch",
              "/invoices/{invoice_id}/receipt","/invoices/{invoice_id}/edit",
              "/invoices/{invoice_id}/cancel",
              "/invoices/{invoice_id}/receipts/{receipt_id}/edit"):
    assert root+route in paths, "Missing route: "+route
for route in ("/purchases/add","/purchases/payments/add",
              "/invoices/create","/invoices/mehr/settle",
              "/invoices/purchases/add","/invoices/{invoice_id}/dispatch",
              "/invoices/{invoice_id}/receipt","/invoices/{invoice_id}/edit",
              "/invoices/{invoice_id}/cancel",
              "/invoices/{invoice_id}/receipts/{receipt_id}/edit"):
    assert "post" in paths[root+route], "Missing POST route: "+route
print("INVOICE_API_ROUTES_OK")
PY

echo "Recreate ONLY Django web and isolated sister sales; leave PostgreSQL untouched."
docker compose -f "$COMPOSE" up -d --no-build --no-deps sister-digikala web

echo "Verify the new invoice pages and schema without inserting customer, stock, or cash records."
docker compose -f "$COMPOSE" exec -T sister-digikala python - <<'PY'
import base64,os,sqlite3,time,urllib.request
secret=os.environ["SALES_ADMIN_PASSWORD"]
account=os.environ.get("SALES_ADMIN_USER","bridge")
auth="Basic "+base64.b64encode((account+":"+secret).encode()).decode()
base="http://127.0.0.1:8018/daily-sales"
for attempt in range(25):
    try:
        with urllib.request.urlopen(base+"/healthz",timeout=4) as res:
            assert res.status==200
        break
    except Exception:
        time.sleep(2)
else:
    raise RuntimeError("Sister service did not become healthy")
for route in ("/purchases","/invoices","/invoices/new","/invoices/mehr","/invoices/purchases",
              "/finance/movements?section=payment","/finance/open-invoices"):
    req=urllib.request.Request(base+route,headers={"Authorization":auth})
    with urllib.request.urlopen(req,timeout=10) as res:
        assert res.status==200,route
        html=res.read(500000)
        assert b"<main" in html,route
        if route=="/finance/movements?section=payment":
            assert b'outgoing-mehr-target-select' in html, "Holder invoice selector missing"
            assert b'id="outgoing-amount" type="text"' in html, "Readable payment amount missing"
        if route=="/invoices/new":
            assert b'id="invoice-gross-profit"' in html, "Invoice profit missing"
        if route=="/invoices":
            assert "ویرایش".encode() in html and "ابطال".encode() in html, "Invoice correction links missing"
    print("INVOICE_HTTP_OK",route)
conn=sqlite3.connect("file:/data/sales.sqlite3?mode=ro",uri=True)
required={"sister_invoice_customers","sister_invoices","sister_invoice_lines",
          "sister_invoice_receipts","sister_mehr_ledger","sister_mehr_purchases",
          "sister_purchase_suppliers","sister_purchase_orders","sister_purchase_lines",
          "sister_purchase_payments","sister_manual_outgoings",
          "sister_mehr_settlement_links","sister_invoice_audit"}
tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert required.issubset(tables),required-tables
columns={r[1] for r in conn.execute("PRAGMA table_info(sister_invoices)")}
assert {"is_void","version","voided_at"}.issubset(columns),columns
print("INVOICE_SCHEMA_READY")
conn.close()
PY
code="$(curl --max-time 10 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/invoices/)"
test "$code" = "302" || { echo "ERROR: Django invoice route login redirect is HTTP $code" >&2; exit 1; }
purchase_code="$(curl --max-time 10 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/purchases/)"
test "$purchase_code" = "302" || { echo "ERROR: Django purchase route login redirect is HTTP $purchase_code" >&2; exit 1; }
echo "DJANGO_PURCHASING_ROUTE_OK"
echo "DJANGO_INVOICE_ROUTE_OK"
echo "INSTALL_DONE version=$(git rev-parse --short HEAD) backup=$STAMP"
docker compose -f "$COMPOSE" ps
