#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=122ac377fffadac4d91e3dd7ba9bce84bbd0a0fe

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, BusinessPayment, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, RawMaterialStock, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer, TakvinPurchase
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
print(f"SALE_SNAPSHOTS={SaleSnapshot.objects.count()}")
print(f"DIA_SALES={DiaGallerySale.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
print(f"PAYMENTS={BusinessPayment.objects.count()}")
print(f"RAW_ROWS={RawMaterialStock.objects.count()}")
print(f"ADJUSTMENTS={InventoryAdjustment.objects.count()}")
print(f"TRANSFERS={StockTransfer.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|SALE_SNAPSHOTS|DIA_SALES|ACCOUNT_ENTRIES|PAYMENTS|RAW_ROWS|ADJUSTMENTS|TRANSFERS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_run() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, BusinessPayment, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, RawMaterialStock, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer, TakvinPurchase
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
print(f"SALE_SNAPSHOTS={SaleSnapshot.objects.count()}")
print(f"DIA_SALES={DiaGallerySale.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
print(f"PAYMENTS={BusinessPayment.objects.count()}")
print(f"RAW_ROWS={RawMaterialStock.objects.count()}")
print(f"ADJUSTMENTS={InventoryAdjustment.objects.count()}")
print(f"TRANSFERS={StockTransfer.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|SALE_SNAPSHOTS|DIA_SALES|ACCOUNT_ENTRIES|PAYMENTS|RAW_ROWS|ADJUSTMENTS|TRANSFERS|MOVEMENTS|TAKVIN_PURCHASES)='
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
BACKUP="backups/before-sale-price-elastic-multi-v60-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
sleep 2
LIVE=$(snapshot_exec) || fail "could not capture live snapshot"
echo "$LIVE"

step "2) VERIFY V60 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V60 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/sale_price_v60.py|core/sale_entry_v60.py|core/daily_order_views_v60.py|core/pricing_v60.py|core/settings_product_v60.py|core/settings_rules_v17.py|core/material_purchase_v60.py|core/business_tools_v60.py|core/static/core/payments_elastic_multi_v60.js|templates/core/settings_product_form_v60.html|templates/core/settings_products_v60.html|templates/core/payments_v60.html|core/management/commands/check_sale_price_elastic_multi_v60.py|core/urls.py|server_sale_price_elastic_multi_v60.sh|docs/PROJECT_CONTEXT/38_SALE_PRICE_ELASTIC_MULTI_V60.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V60 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations \
  core/darma_cost_v55.py core/novani_cost_v59.py core/takvin_pricing_v17.py core/takvin_v5.py \
  core/inventory_valuation_v17.py core/inventory_v20.py core/final_services.py core/finance.py core/cost_accounting_v14.py \
  core/business_tools_v22.py core/material_purchase_v13.py core/material_purchase_v14.py core/material_flow.py \
  core/daily_order_import_v23.py core/daily_report_v8.py core/daily_report_actions_v21.py core/sale_inventory_v19.py \
  || fail "protected non-V60 business source changed"

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
docker compose run --rm --entrypoint python web manage.py check_sale_price_elastic_multi_v60 || fail "V60 regression failed"

step "4) CARRY FORWARD V59 TAKVIN PURCHASE REPAIR (IDEMPOTENT)"
DRY=$(docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 2>/dev/null) || fail "V59 Takvin repair dry-run failed"
echo "$DRY"
ADD_QTY=$(echo "$DRY" | sed -n 's/^TAKVIN_REPAIR_ADD_QTY=//p' | tail -1)
ADD_VALUE=$(echo "$DRY" | sed -n 's/^TAKVIN_REPAIR_EXPECTED_FINISHED_DELTA=//p' | tail -1)
[ -n "$ADD_QTY" ] || fail "V59 repair dry-run did not report quantity"
[ -n "$ADD_VALUE" ] || fail "V59 repair dry-run did not report valuation"

BEFORE_REPAIR=$(snapshot_exec) || fail "could not capture pre-repair snapshot"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 --apply || fail "V59 Takvin repair apply failed"
AFTER_REPAIR=$(snapshot_exec) || fail "could not capture post-repair snapshot"
echo "$AFTER_REPAIR"

B_FIN=$(val "$BEFORE_REPAIR" FINISHED); A_FIN=$(val "$AFTER_REPAIR" FINISHED)
B_CAP=$(val "$BEFORE_REPAIR" CAPITAL); A_CAP=$(val "$AFTER_REPAIR" CAPITAL)
B_TAK=$(val "$BEFORE_REPAIR" TAKVIN); A_TAK=$(val "$AFTER_REPAIR" TAKVIN)
[ $((A_FIN-B_FIN)) -eq "$ADD_VALUE" ] || fail "V59 repair finished-value delta mismatch"
[ $((A_CAP-B_CAP)) -eq "$ADD_VALUE" ] || fail "V59 repair capital delta mismatch"
[ $((A_TAK-B_TAK)) -eq "$ADD_QTY" ] || fail "V59 repair Takvin quantity delta mismatch"
for k in RAW DIGI DIA TAKVIN_DEBT DARMA NOVANI SALE_DAYS SALES SALE_SNAPSHOTS DIA_SALES ACCOUNT_ENTRIES PAYMENTS RAW_ROWS ADJUSTMENTS TRANSFERS TAKVIN_PURCHASES; do
  [ "$(val "$BEFORE_REPAIR" "$k")" = "$(val "$AFTER_REPAIR" "$k")" ] || fail "V59 repair unexpectedly changed $k"
done

step "5) PROJECT NEW V60 LIVE STATE"
PROJECTED=$(snapshot_run) || fail "could not calculate V60 projected snapshot"
echo "$PROJECTED"

step "6) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_cost_rules_takvin_purchase_v59 || fail "live V59 regression failed"
docker compose exec -T web python manage.py check_sale_price_elastic_multi_v60 || fail "live V60 regression failed"

step "7) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final snapshot"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED V60 ---"; echo "$PROJECTED"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "live V60 snapshot differs from projected new-code state"
}

step "8) SUCCESS"
echo "SUCCESS: SALE PRICE + ELASTIC MULTI V60 DEPLOYED"
if [ "$ADD_QTY" -gt 0 ]; then
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK V59 REPAIRED"
  echo "TAKVIN_REPAIRED_QTY=$ADD_QTY"
  echo "TAKVIN_REPAIRED_VALUE=$ADD_VALUE"
else
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK ALREADY CLEAN"
fi
echo "Backup: $BACKUP"
echo "Darma/Takvin sale prices: date-effective; existing SaleLine prices stay frozen."
echo "Elastic purchases: one payment can contain multiple colors and both 16/25 variants."
