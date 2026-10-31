#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=c56991f3eda44094f9d0c4eedba8c2f37fd402bb

snapshot_business() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

dia=int(dia_gallery_receivable_total())
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
print(f"SALE_DAYS={SaleDay.objects.count()}")
print(f"SALES={SaleLine.objects.count()}")
print(f"DIA_SALES={DiaGallerySale.objects.count()}")
print(f"SALE_SNAPSHOTS={SaleSnapshot.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
print(f"ADJUSTMENTS={InventoryAdjustment.objects.count()}")
print(f"TRANSFERS={StockTransfer.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|DIA_SALES|SALE_SNAPSHOTS|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS)='
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
BACKUP="backups/before-daily-sale-day-delete-v54-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) CAPTURE LIVE BUSINESS SNAPSHOT"
docker compose up -d web || fail "web start failed"
sleep 3
LIVE=$(snapshot_business) || fail "could not capture live business snapshot"
echo "$LIVE"

step "3) VERIFY V54 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V54 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/daily_report_actions_v21.py|core/urls.py|templates/core/daily_report_v21.html|core/management/commands/check_daily_sale_day_delete_v54.py|server_daily_sale_day_delete_v54.sh|docs/PROJECT_CONTEXT/32_DAILY_SALE_DAY_DELETE_V54.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V54 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations \
  core/final_services.py core/sale_inventory_v19.py core/variant_sale_v12.py core/dia_gallery_v45.py \
  core/finance.py core/finance_excel_v9.py core/cost_accounting_v14.py core/inventory_valuation_v17.py \
  core/daily_order_import_v23.py core/daily_order_views_v8.py core/daily_report_v8.py \
  core/report_v9.py core/business_tools_v22.py core/material_report_v22.py core/returns_v37.py core/calculator_v37.py \
  core/inventory_operations_v15.py core/inventory_v20.py \
  || fail "protected business/ledger/inventory source changed in V54"

step "4) BUILD + READ-ONLY/ROLLBACK PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
# V48 renders templates that resolve ManifestStaticFilesStorage URLs. Because the
# one-off preflight intentionally bypasses entrypoint.sh, collectstatic has not run
# inside that container yet. Run collectstatic + the V48 regression in the SAME
# ephemeral container so the manifest exists without touching business data.
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 daily-report runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_operations_v50 || fail "V50 inventory regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_operations_v51 || fail "V51 adjustment-delete regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_highlights_v52 || fail "V52 inventory-highlight regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_highlights_v53 || fail "V53 inventory-red-strength regression failed"
docker compose run --rm --entrypoint python web manage.py check_daily_sale_day_delete_v54 || fail "V54 full-day delete regression failed"

step "5) VERIFY PREFLIGHT CHANGED NOTHING"
PREFLIGHT=$(snapshot_business) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- AFTER PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "V54 preflight changed persistent business data"
}

step "6) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6
docker compose exec -T web python manage.py migrate --check || fail "migration check failed"
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_daily_report_runtime_v48 || fail "live V48 daily-report runtime regression failed"
docker compose exec -T web python manage.py check_inventory_operations_v50 || fail "live V50 inventory regression failed"
docker compose exec -T web python manage.py check_inventory_operations_v51 || fail "live V51 adjustment-delete regression failed"
docker compose exec -T web python manage.py check_inventory_highlights_v52 || fail "live V52 inventory-highlight regression failed"
docker compose exec -T web python manage.py check_inventory_highlights_v53 || fail "live V53 inventory-red-strength regression failed"
docker compose exec -T web python manage.py check_daily_sale_day_delete_v54 || fail "live V54 full-day delete regression failed"

step "7) VERIFY DEPLOYMENT CHANGED NO BUSINESS VALUES"
FINAL=$(snapshot_business) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE V54 ---"; echo "$LIVE"
  echo "--- AFTER V54 ---"; echo "$FINAL"
  fail "V54 deployment changed business/accounting/inventory values"
}

step "8) SUCCESS"
echo "SUCCESS: DAILY SALE DAY DELETE V54 DEPLOYED"
echo "Backup: $BACKUP"
echo "Button: daily report -> beside sales calendar -> delete daily report"
echo "Delete behavior: reverse SaleLine + s3 + Anbaresh + Dia inventory/receivables, then delete SaleDay"
echo "Unrelated same-date payments/expenses/production/materials/manual stock operations: untouched"
