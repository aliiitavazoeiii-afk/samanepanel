#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=47abb27b5b311baf7d0b96e891cd6b3059b2db2e
SECRET_ROOT=/opt/darma-secrets/digikala
RUNTIME_SECRET="$SECRET_ROOT/runtime"

step "1) PREPARE ISOLATED DIGIKALA RUNTIME SECRETS"
[ -d "$SECRET_ROOT" ] || fail "Digikala secret directory not found: $SECRET_ROOT"
[ -s "$SECRET_ROOT/access_token.txt" ] || [ -s "$RUNTIME_SECRET/access_token.txt" ] || fail "Digikala access_token.txt not found"
[ -s "$SECRET_ROOT/refresh_token.txt" ] || [ -s "$RUNTIME_SECRET/refresh_token.txt" ] || fail "Digikala refresh_token.txt not found"
mkdir -p "$RUNTIME_SECRET"
chmod 700 "$RUNTIME_SECRET"
if [ ! -s "$RUNTIME_SECRET/access_token.txt" ]; then cp "$SECRET_ROOT/access_token.txt" "$RUNTIME_SECRET/access_token.txt"; fi
if [ ! -s "$RUNTIME_SECRET/refresh_token.txt" ]; then cp "$SECRET_ROOT/refresh_token.txt" "$RUNTIME_SECRET/refresh_token.txt"; fi
if [ ! -s "$RUNTIME_SECRET/token_meta.json" ] && [ -s "$SECRET_ROOT/token_meta.json" ]; then cp "$SECRET_ROOT/token_meta.json" "$RUNTIME_SECRET/token_meta.json"; fi
chmod 600 "$RUNTIME_SECRET/access_token.txt" "$RUNTIME_SECRET/refresh_token.txt"
[ ! -e "$RUNTIME_SECRET/private_key.pem" ] || fail "private key must not be placed in runtime token directory"

echo "Runtime token directory ready; RSA private key remains outside the web mount."

step "2) START DATABASE"
docker compose config -q || fail "docker compose configuration is invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "3) FULL DATABASE BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-digikala-readonly-v40-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

snapshot_live() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
print(f"CAPITAL={capital}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null
}

snapshot_new() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
print(f"CAPITAL={capital}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null
}

step "4) CAPTURE LIVE BUSINESS VALUES"
LIVE=$(snapshot_live) || fail "could not read live business values"
echo "$LIVE"

step "5) V40 SOURCE-SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-v40 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/digikala_client_v40.py|core/digikala_views_v40.py|core/management/commands/check_digikala_v40.py|core/urls.py|templates/core/digikala_v40.html|templates/core/dashboard_excel.html|static/core/number_format.js|compose.yml|server_digikala_readonly_v40.sh|UI_SAFETY_V40.md|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/03_ACTIVE_CODE_MAP.md|docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md|docs/PROJECT_CONTEXT/09_UI_AND_USER_WORKFLOW_CONTRACT.md|docs/PROJECT_CONTEXT/12_VERSION_TIMELINE_V18_TO_V37.md|docs/PROJECT_CONTEXT/18_DIGIKALA_API_V40.md) ;;
    *) fail "unexpected V40 file changed: $f" ;;
  esac
done

# Frozen accounting / stock / sales / materials / payments implementation files.
git diff --quiet "$BASE"..HEAD -- core/finance.py core/report_v9.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/final_services.py core/cost_accounting_v14.py core/finance_excel_v9.py core/daily_order_import_v23.py core/returns_v37.py core/calculator_v37.py core/models.py core/migrations || fail "protected business source changed in V40"

step "6) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "7) PREFLIGHT — DJANGO / ROUTES / READ-ONLY API"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 operational regression check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_v40 --live || fail "V40 Digikala read-only check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
client=Path("/app/core/digikala_client_v40.py").read_text(encoding="utf-8")
views=Path("/app/core/digikala_views_v40.py").read_text(encoding="utf-8")
urls=Path("/app/core/urls.py").read_text(encoding="utf-8")
dash=Path("/app/templates/core/dashboard_excel.html").read_text(encoding="utf-8")
nav=Path("/app/static/core/number_format.js").read_text(encoding="utf-8")
compose=Path("/app/compose.yml").read_text(encoding="utf-8")
assert "@require_GET" in views
assert "digikala_views_v40.digikala_home" in urls
assert "digikala_views_v40.digikala_summary" in urls
assert "digikalaLiveCard" in dash and "digikala_summary" in dash
assert "data-digikala-nav" in nav or "dataset.digikalaNav" in nav
assert "/opt/darma-secrets/digikala/runtime:/run/secrets/digikala" in compose
for forbidden in ["/open-api/v1/orders/", "/open-api/v1/inventories/"]:
    pass
assert "_request_once(\"GET\"" in client
assert "\"POST\",\n            \"/open-api/v1/auth/refresh-token\"" in client
assert "/open-api/v1/insight/overview" not in client
assert "/open-api/v1/insight/sales-reports" not in client
assert Path("/run/secrets/digikala/access_token.txt").is_file()
assert Path("/run/secrets/digikala/refresh_token.txt").is_file()
assert not Path("/run/secrets/digikala/private_key.pem").exists()
assert Path("/app/static/core/ui-v39.css").is_file(), "V39 stylesheet missing from image"
assert Path("/app/static/core/darma-logo-v39.webp").is_file(), "V39 logo missing from image"
print("V40 SOURCE / SECRET-ISOLATION SAFETY CHECK OK")
' || fail "V40 source safety check failed"

step "8) VERIFY PREFLIGHT CHANGED NO BUSINESS VALUES"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during V40 build/preflight"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 regression check failed"
docker compose exec -T web python manage.py check_digikala_v40 --live || fail "live V40 Digikala check failed"

step "10) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V40 read-only integration changed business values"

echo ""
echo "======================================"
echo "SUCCESS: DIGIKALA READ-ONLY V40 DEPLOYED"
echo "Backup: $BACKUP"
echo "Digikala API: authenticated and read-only dashboard integration enabled"
echo "Token refresh: automatic; rotated refresh token is persisted atomically"
echo "RSA private key: NOT mounted into the web container"
echo "Insight endpoints: intentionally excluded after real HTTP 500/400 probe"
echo "Accounting/inventory/sales/import/material/payment/return/calculator semantics: unchanged"
echo "All protected economic invariants: unchanged"
echo "======================================"
