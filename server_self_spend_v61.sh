#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=c6f9ee61dce346448e044ef61f0bb7c0277cd30d

snapshot_run() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
dia=int(dia_gallery_receivable_total())
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
mellat=next((int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS) if "ملت" in (x.title or "").replace(" ","")),0)
self_qs=BusinessPayment.objects.filter(payee="self")
self_total=int(self_qs.aggregate(v=Sum("amount"))["v"] or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"MELLAT={mellat}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"TAKVIN_DEBT={debt}")
print(f"DARMA_QTY={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN_QTY={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI_QTY={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"PAYMENTS={BusinessPayment.objects.count()}")
print(f"SELF_PAYMENTS={self_qs.count()}")
print(f"SELF_TOTAL={self_total}")
print(f"RAW_ROWS={RawMaterialStock.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|FINISHED|RAW|DIGI|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|SELF_PAYMENTS|SELF_TOTAL|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
dia=int(dia_gallery_receivable_total())
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
mellat=next((int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS) if "ملت" in (x.title or "").replace(" ","")),0)
self_qs=BusinessPayment.objects.filter(payee="self")
self_total=int(self_qs.aggregate(v=Sum("amount"))["v"] or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"MELLAT={mellat}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"TAKVIN_DEBT={debt}")
print(f"DARMA_QTY={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN_QTY={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI_QTY={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"PAYMENTS={BusinessPayment.objects.count()}")
print(f"SELF_PAYMENTS={self_qs.count()}")
print(f"SELF_TOTAL={self_total}")
print(f"RAW_ROWS={RawMaterialStock.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
print(f"TAKVIN_PURCHASES={TakvinPurchase.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|FINISHED|RAW|DIGI|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|SELF_PAYMENTS|SELF_TOTAL|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

step "1) DATABASE BACKUP"
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
BACKUP="backups/before-self-spend-v61-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) VERIFY V61 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V61 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/business_tools_v61.py|templates/core/payments_v61.html|core/management/commands/check_self_spend_v61.py|core/urls.py|server_self_spend_v61.sh) ;;
    *) fail "unexpected V61 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations \
  core/business_tools_v60.py core/material_purchase_v60.py core/sale_price_v60.py \
  core/darma_cost_v55.py core/novani_cost_v59.py core/inventory_valuation_v17.py \
  || fail "protected business source changed"

step "3) BUILD + REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 regression failed"
docker compose run --rm --entrypoint python web manage.py check_sale_price_elastic_multi_v60 || fail "V60 regression failed"
docker compose run --rm --entrypoint python web manage.py check_self_spend_v61 || fail "V61 regression failed"

step "4) CARRY FORWARD V59 TAKVIN PURCHASE REPAIR (IDEMPOTENT)"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 || fail "V59 Takvin repair dry-run failed"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 --apply || fail "V59 Takvin repair apply failed"

step "5) PROJECT NEW-CODE BUSINESS STATE"
PROJECTED=$(snapshot_run) || fail "could not capture projected V61 state"
echo "$PROJECTED"

step "6) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_cost_rules_takvin_purchase_v59 || fail "live V59 regression failed"
docker compose exec -T web python manage.py check_sale_price_elastic_multi_v60 || fail "live V60 regression failed"
docker compose exec -T web python manage.py check_self_spend_v61 || fail "live V61 regression failed"

step "7) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V61 state"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED ---"
  echo "$PROJECTED"
  echo "--- FINAL ---"
  echo "$FINAL"
  fail "live V61 state differs from projected state"
}

step "8) SUCCESS"
echo "SUCCESS: SELF SPEND V61 DEPLOYED"
echo "Backup: $BACKUP"
echo "Personal spend: subtracts exact amount from Mellat, lowers capital by same amount, and is tracked under خودم."
echo "Finished inventory, raw materials, Digikala receivable and Takvin debt are not touched by a self payment."
