#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=5a90a2eeb35cca2246eb61b046c1bc46e3690b11

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

step "1) DATABASE BACKUP + LIVE BUSINESS SNAPSHOT"
docker compose config -q || fail "compose invalid"
docker compose up -d db web || fail "database/web start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1
  i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-returns-report-edit-delete-v57-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
sleep 2
LIVE=$(snapshot_business) || fail "could not capture live business snapshot"
echo "$LIVE"

step "2) VERIFY V57 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V57 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/returns_v37.py|templates/core/returns_v37.html|core/urls.py|core/management/commands/check_returns_history_v57.py|server_returns_report_edit_delete_v57.sh|docs/PROJECT_CONTEXT/35_RETURNS_REPORT_EDIT_DELETE_V57.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V57 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations core/final_services.py \
  core/darma_cost_v55.py core/cost_accounting_v14.py core/inventory_valuation_v17.py \
  core/dia_gallery_v45.py core/finance.py core/finance_excel_v9.py core/report_v9.py \
  core/inventory_v20.py core/inventory_operations_v15.py core/sale_inventory_v19.py \
  core/variant_sale_v12.py core/daily_order_import_v23.py core/daily_order_views_v8.py \
  core/daily_report_v8.py core/daily_report_actions_v21.py core/business_tools_v22.py \
  || fail "protected non-V57 business source changed"

step "3) BUILD + TRANSACTIONAL REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 returns regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_darma_cost_v56 || fail "V56 inventory-page regression failed"
docker compose run --rm --entrypoint python web manage.py check_returns_history_v57 || fail "V57 returns history regression failed"

step "4) VERIFY PREFLIGHT CHANGED NO BUSINESS DATA"
PREFLIGHT=$(snapshot_business) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- AFTER PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "V57 preflight changed persistent business data"
}

step "5) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 returns regression failed"
docker compose exec -T web python manage.py check_darma_cost_rule_v55 || fail "live V55 Darma cost regression failed"
docker compose exec -T web python manage.py check_inventory_darma_cost_v56 || fail "live V56 inventory-page regression failed"
docker compose exec -T web python manage.py check_returns_history_v57 || fail "live V57 returns history regression failed"

step "6) VERIFY EXISTING RETURN HISTORY IS READABLE"
docker compose exec -T web python manage.py shell -c '
from core.returns_v37 import _return_history
rows=_return_history()
print(f"RETURN_REPORT_GROUPS={len(rows)}")
for row in rows[:5]:
    date_j=row["date_j"]
    brand=row["brand"].name
    size=row["size"].name
    mode=row["mode"]
    shorts=row["shorts"]
    group=row["group"]
    safe=row["safe"]
    print(f"RETURN_REPORT={date_j}|{brand}|{size}|{mode}|{shorts}|{group}|safe={safe}")
' || fail "existing return history could not be reconstructed"

step "7) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_business) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "V57 deploy changed business data; deployment itself must be read-only"
}

step "8) SUCCESS"
echo "SUCCESS: RETURNS REPORT EDIT DELETE V57 DEPLOYED"
echo "Backup: $BACKUP"
echo "Existing standalone-return V37 groups are now visible under Returns."
echo "Delete/edit actions run only when the exact return adjustments and movements match."
