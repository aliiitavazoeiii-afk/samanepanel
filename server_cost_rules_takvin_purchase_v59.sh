#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=bc161dcc4071e8f8acab610e6d848bd86d057095

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer, TakvinPurchase
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
print(f"TAKVIN_DEBT={debt}")
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
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|DIA_SALES|SALE_SNAPSHOTS|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_run() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer, TakvinPurchase
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
print(f"TAKVIN_DEBT={debt}")
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
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|DIA_SALES|SALE_SNAPSHOTS|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS|TAKVIN_PURCHASES)='
}

val(){ echo "$1" | sed -n "s/^$2=//p" | tail -1; }

step "1) DATABASE BACKUP + LIVE SNAPSHOT"
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
BACKUP="backups/before-cost-rules-takvin-purchase-v59-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
sleep 2
LIVE=$(snapshot_exec) || fail "could not capture live snapshot"
echo "$LIVE"

step "2) VERIFY V59 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V59 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/novani_cost_v59.py|core/settings_rules_v17.py|templates/core/settings_rules_v17.html|core/inventory_valuation_v17.py|core/inventory_v20.py|templates/core/inventory_v19.html|core/finance.py|core/cost_accounting_v14.py|templates/core/settings_product_form.html|core/takvin_v5.py|core/management/commands/repair_takvin_purchase_stock_v59.py|core/management/commands/check_cost_rules_takvin_purchase_v59.py|server_cost_rules_takvin_purchase_v59.sh|docs/PROJECT_CONTEXT/37_COST_RULES_TAKVIN_PURCHASE_V59.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V59 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/models.py core/models_final.py core/migrations core/urls.py core/final_services.py core/material_report_v20.py core/material_report_v22.py core/business_tools_v22.py || fail "protected source changed unexpectedly"

step "3) BUILD + REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_darma_cost_v56 || fail "V56 inventory regression failed"
docker compose run --rm --entrypoint python web manage.py check_returns_history_v57 || fail "V57 return history regression failed"
docker compose run --rm --entrypoint python web manage.py check_returns_multisize_v58 || fail "V58 multi-size return regression failed"
docker compose run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 regression failed"

step "4) DRY-RUN TODAY TAKVIN PURCHASE REPAIR"
DRY=$(docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 2>/dev/null) || fail "Takvin purchase repair dry-run failed"
echo "$DRY"
ADD_QTY=$(echo "$DRY" | sed -n 's/^TAKVIN_REPAIR_ADD_QTY=//p' | tail -1)
ADD_VALUE=$(echo "$DRY" | sed -n 's/^TAKVIN_REPAIR_EXPECTED_FINISHED_DELTA=//p' | tail -1)
[ -n "$ADD_QTY" ] || fail "repair dry-run did not report quantity"
[ -n "$ADD_VALUE" ] || fail "repair dry-run did not report expected valuation"

step "5) APPLY ONLY MISSING TODAY TAKVIN PURCHASE STOCK"
BEFORE_REPAIR=$(snapshot_exec) || fail "could not capture pre-repair snapshot"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 --apply || fail "Takvin purchase stock repair failed"
AFTER_REPAIR=$(snapshot_exec) || fail "could not capture post-repair snapshot"
echo "$AFTER_REPAIR"

B_FIN=$(val "$BEFORE_REPAIR" FINISHED); A_FIN=$(val "$AFTER_REPAIR" FINISHED)
B_CAP=$(val "$BEFORE_REPAIR" CAPITAL); A_CAP=$(val "$AFTER_REPAIR" CAPITAL)
B_TAK=$(val "$BEFORE_REPAIR" TAKVIN); A_TAK=$(val "$AFTER_REPAIR" TAKVIN)
[ $((A_FIN-B_FIN)) -eq "$ADD_VALUE" ] || fail "Takvin repair finished-value delta mismatch"
[ $((A_CAP-B_CAP)) -eq "$ADD_VALUE" ] || fail "Takvin repair capital delta mismatch"
[ $((A_TAK-B_TAK)) -eq "$ADD_QTY" ] || fail "Takvin repair quantity delta mismatch"
for k in RAW DIGI DIA TAKVIN_DEBT DARMA NOVANI SALE_DAYS SALES DIA_SALES SALE_SNAPSHOTS ACCOUNT_ENTRIES ADJUSTMENTS TRANSFERS TAKVIN_PURCHASES; do
  [ "$(val "$BEFORE_REPAIR" "$k")" = "$(val "$AFTER_REPAIR" "$k")" ] || fail "Takvin repair unexpectedly changed $k"
done
# Each repaired purchase row gets one purchase movement.
[ $(( $(val "$AFTER_REPAIR" MOVEMENTS) - $(val "$BEFORE_REPAIR" MOVEMENTS) )) -ge 0 ] || fail "movement count decreased during repair"

step "6) PROJECT NEW V59 VALUATION BEFORE LIVE RECREATE"
PROJECTED=$(snapshot_run) || fail "could not calculate V59 projected snapshot"
echo "$PROJECTED"

step "7) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_cost_rules_takvin_purchase_v59 || fail "live V59 regression failed"

step "8) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final snapshot"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED V59 ---"; echo "$PROJECTED"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "live V59 snapshot differs from projected new-code state"
}

step "9) SUCCESS"
echo "SUCCESS: NOVANI COST RULE + TAKVIN PURCHASE V59 DEPLOYED"
if [ "$ADD_QTY" -gt 0 ]; then
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK V59 REPAIRED"
  echo "TAKVIN_REPAIRED_QTY=$ADD_QTY"
  echo "TAKVIN_REPAIRED_VALUE=$ADD_VALUE"
else
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK ALREADY CLEAN"
fi
echo "Backup: $BACKUP"
echo "Darma and Novani dated costs are managed from Settings -> Rules."
