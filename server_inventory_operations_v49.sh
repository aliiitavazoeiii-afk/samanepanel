#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=274aeaf885d00b331502ff03b3bb7c9e908d80d3

snapshot_business() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, SaleLine, StockBalance, StockTransfer
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
try:
    from core.dia_gallery_v45 import dia_gallery_receivable_total
    dia=int(dia_gallery_receivable_total())
except Exception:
    dia=0
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DIA={dia}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
print(f"ADJUSTMENTS={InventoryAdjustment.objects.count()}")
print(f"TRANSFERS={StockTransfer.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALES|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS)='
}

step "1) START DATABASE + BACKUP"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1
  i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-inventory-operations-v49-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) CAPTURE LIVE BUSINESS SNAPSHOT"
docker compose up -d web || fail "web start failed"
sleep 3
LIVE=$(snapshot_business) || fail "could not capture live business snapshot"
echo "$LIVE"

step "3) VERIFY V49 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V49 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/inventory_operations_v15.py|templates/core/inventory_operations.html|core/management/commands/check_inventory_operations_v49.py|server_inventory_operations_v49.sh|docs/PROJECT_CONTEXT/27_INVENTORY_OPERATIONS_V49.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/05_INVENTORY_MATERIALS_PRODUCTION_PAYMENTS.md|docs/00_NEW_CHAT_READ_FIRST.md) ;;
    *) fail "unexpected V49 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/models.py core/models_final.py core/migrations core/final_services.py core/finance.py core/finance_excel_v9.py core/inventory_valuation_v17.py core/report_v9.py core/daily_order_import_v23.py core/business_tools_v22.py core/material_report_v22.py core/returns_v37.py core/calculator_v37.py || fail "protected business/model/formula source changed in V49"

step "4) BUILD + PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py shell -c 'from django.template.loader import get_template; get_template("core/inventory_operations.html"); print("INVENTORY OPERATIONS TEMPLATE OK")' || fail "inventory operations template compile failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_operations_v49 || fail "V49 rollback regression failed"

step "5) VERIFY PREFLIGHT LEFT BUSINESS STATE UNCHANGED"
PREFLIGHT=$(snapshot_business) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- AFTER PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "V49 preflight changed persistent business data"
}

step "6) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6
docker compose exec -T web python manage.py migrate --check || fail "migration check failed"
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_inventory_operations_v49 || fail "live V49 regression failed"

step "7) VERIFY DEPLOYMENT CHANGED NO BUSINESS VALUES"
FINAL=$(snapshot_business) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE V49 ---"; echo "$LIVE"
  echo "--- AFTER V49 ---"; echo "$FINAL"
  fail "V49 deployment changed business/accounting/inventory values"
}

step "8) SUCCESS"
echo "SUCCESS: INVENTORY OPERATIONS V49 DEPLOYED"
echo "Backup: $BACKUP"
echo "Adjustment input: absolute final stock; internal audit remains delta-based"
echo "Transfer input: one size + all Darma colors, fixed KHORSHID -> HOME"
echo "Transfer batch: atomic; blank/zero colors ignored"
echo "Models/formulas/accounting/sales: unchanged"
