#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=a8f5d07713bb984ac9497ee7e53d125a662d1259

snapshot_run() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.business_tools_v21 import mellat_balance
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context
from core.self_spend_v62 import expected_self_total,manual_accounts_capital_total,self_tracking_row

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
dia=int(dia_gallery_receivable_total())
manual=int(manual_accounts_capital_total())
assets=int(rows.filter(section=ExcelManualRow.ASSETS).aggregate(v=Sum("amount"))["v"] or 0)
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
selfrow=self_tracking_row(create=False)
selftrack=int(selfrow.amount or 0) if selfrow else 0
selfcount=BusinessPayment.objects.filter(payee="self").count()
selftotal=int(expected_self_total())
capital=manual+dia+assets+finished+raw+digi-debt
print("CAPITAL=%d" % capital)
print("MELLAT=%d" % int(mellat_balance()))
print("FINISHED=%d" % finished)
print("RAW=%d" % raw)
print("DIGI=%d" % digi)
print("DIA=%d" % dia)
print("TAKVIN_DEBT=%d" % debt)
print("DARMA_QTY=%d" % bqty("دارما"))
print("TAKVIN_QTY=%d" % bqty("تکوین"))
print("NOVANI_QTY=%d" % bqty("Novani"))
print("SALES=%d" % SaleLine.objects.count())
print("PAYMENTS=%d" % BusinessPayment.objects.count())
print("SELF_PAYMENTS=%d" % selfcount)
print("SELF_PAYMENT_TOTAL=%d" % selftotal)
print("SELF_TRACKING=%d" % selftrack)
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|SELF_PAYMENTS|SELF_PAYMENT_TOTAL|SELF_TRACKING|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.business_tools_v21 import mellat_balance
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context
from core.self_spend_v62 import expected_self_total,manual_accounts_capital_total,self_tracking_row

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
dia=int(dia_gallery_receivable_total())
manual=int(manual_accounts_capital_total())
assets=int(rows.filter(section=ExcelManualRow.ASSETS).aggregate(v=Sum("amount"))["v"] or 0)
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
selfrow=self_tracking_row(create=False)
selftrack=int(selfrow.amount or 0) if selfrow else 0
selfcount=BusinessPayment.objects.filter(payee="self").count()
selftotal=int(expected_self_total())
capital=manual+dia+assets+finished+raw+digi-debt
print("CAPITAL=%d" % capital)
print("MELLAT=%d" % int(mellat_balance()))
print("FINISHED=%d" % finished)
print("RAW=%d" % raw)
print("DIGI=%d" % digi)
print("DIA=%d" % dia)
print("TAKVIN_DEBT=%d" % debt)
print("DARMA_QTY=%d" % bqty("دارما"))
print("TAKVIN_QTY=%d" % bqty("تکوین"))
print("NOVANI_QTY=%d" % bqty("Novani"))
print("SALES=%d" % SaleLine.objects.count())
print("PAYMENTS=%d" % BusinessPayment.objects.count())
print("SELF_PAYMENTS=%d" % selfcount)
print("SELF_PAYMENT_TOTAL=%d" % selftotal)
print("SELF_TRACKING=%d" % selftrack)
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|SELF_PAYMENTS|SELF_PAYMENT_TOTAL|SELF_TRACKING|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

val(){ echo "$1" | sed -n "s/^$2=//p" | tail -1; }

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
BACKUP="backups/before-self-payee-account-v62-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) VERIFY V62 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V62 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/business_tools_v62.py|core/self_spend_v62.py|core/report_v10.py|templates/core/payments_v62.html|core/management/commands/check_self_payee_account_v62.py|core/management/commands/repair_self_tracking_v62.py|core/management/commands/check_sale_price_elastic_multi_v60.py|core/urls.py|server_self_payee_account_v62.sh) ;;
    *) fail "unexpected V62 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations \
  core/business_tools_v60.py core/material_purchase_v60.py core/sale_price_v60.py \
  core/darma_cost_v55.py core/novani_cost_v59.py core/inventory_valuation_v17.py \
  core/takvin_v5.py core/finance.py core/cost_accounting_v14.py \
  || fail "protected business source changed"

step "3) BUILD + REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 regression failed"
docker compose run --rm --entrypoint python web manage.py check_sale_price_elastic_multi_v60 || fail "V60 regression failed"
docker compose run --rm --entrypoint python web manage.py check_self_payee_account_v62 || fail "V62 regression failed"

step "4) CARRY FORWARD V59 TAKVIN PURCHASE REPAIR (IDEMPOTENT)"
DRY_TAK=$(docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 2>/dev/null) || fail "V59 Takvin repair dry-run failed"
echo "$DRY_TAK"
ADD_QTY=$(echo "$DRY_TAK" | sed -n 's/^TAKVIN_REPAIR_ADD_QTY=//p' | tail -1)
ADD_VALUE=$(echo "$DRY_TAK" | sed -n 's/^TAKVIN_REPAIR_EXPECTED_FINISHED_DELTA=//p' | tail -1)
[ -n "$ADD_QTY" ] || fail "V59 repair dry-run did not report quantity"
[ -n "$ADD_VALUE" ] || fail "V59 repair dry-run did not report valuation"
BEFORE_TAK=$(snapshot_run) || fail "could not capture pre-V59-repair state"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 --apply || fail "V59 Takvin repair apply failed"
AFTER_TAK=$(snapshot_run) || fail "could not capture post-V59-repair state"
B_FIN=$(val "$BEFORE_TAK" FINISHED); A_FIN=$(val "$AFTER_TAK" FINISHED)
B_CAP=$(val "$BEFORE_TAK" CAPITAL); A_CAP=$(val "$AFTER_TAK" CAPITAL)
B_TAK=$(val "$BEFORE_TAK" TAKVIN_QTY); A_TAK=$(val "$AFTER_TAK" TAKVIN_QTY)
[ $((A_FIN-B_FIN)) -eq "$ADD_VALUE" ] || fail "V59 repair finished-value delta mismatch"
[ $((A_CAP-B_CAP)) -eq "$ADD_VALUE" ] || fail "V59 repair capital delta mismatch"
[ $((A_TAK-B_TAK)) -eq "$ADD_QTY" ] || fail "V59 repair Takvin quantity delta mismatch"
for k in MELLAT RAW DIGI DIA TAKVIN_DEBT DARMA_QTY NOVANI_QTY SALES PAYMENTS SELF_PAYMENTS SELF_PAYMENT_TOTAL RAW_ROWS TAKVIN_PURCHASES; do
  [ "$(val "$BEFORE_TAK" "$k")" = "$(val "$AFTER_TAK" "$k")" ] || fail "V59 repair unexpectedly changed $k"
done

step "5) RECONCILE EXISTING SELF PAYMENTS INTO حساب‌ها/خودم"
DRY_SELF=$(docker compose run --rm --entrypoint python web manage.py repair_self_tracking_v62 2>/dev/null) || fail "V62 self tracking dry-run failed"
echo "$DRY_SELF"
EXPECTED_SELF=$(echo "$DRY_SELF" | sed -n 's/^SELF_TRACKING_EXPECTED=//p' | tail -1)
[ -n "$EXPECTED_SELF" ] || fail "V62 self tracking dry-run missing expected total"
BEFORE_SELF=$(snapshot_run) || fail "could not capture pre-self-reconcile state"
docker compose run --rm --entrypoint python web manage.py repair_self_tracking_v62 --apply || fail "V62 self tracking reconcile failed"
AFTER_SELF=$(snapshot_run) || fail "could not capture post-self-reconcile state"
[ "$(val "$AFTER_SELF" SELF_TRACKING)" = "$EXPECTED_SELF" ] || fail "V62 self tracking final total mismatch"
[ "$(val "$AFTER_SELF" SELF_TRACKING)" = "$(val "$AFTER_SELF" SELF_PAYMENT_TOTAL)" ] || fail "V62 tracker does not equal recorded self payments"
for k in CAPITAL MELLAT FINISHED RAW DIGI DIA TAKVIN_DEBT DARMA_QTY TAKVIN_QTY NOVANI_QTY SALES PAYMENTS SELF_PAYMENTS SELF_PAYMENT_TOTAL RAW_ROWS MOVEMENTS TAKVIN_PURCHASES; do
  [ "$(val "$BEFORE_SELF" "$k")" = "$(val "$AFTER_SELF" "$k")" ] || fail "V62 self reconcile unexpectedly changed $k"
done

step "6) PROJECT NEW V62 LIVE STATE"
PROJECTED=$(snapshot_run) || fail "could not calculate V62 projected state"
echo "$PROJECTED"

step "7) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_cost_rules_takvin_purchase_v59 || fail "live V59 regression failed"
docker compose exec -T web python manage.py check_sale_price_elastic_multi_v60 || fail "live V60 regression failed"
docker compose exec -T web python manage.py check_self_payee_account_v62 || fail "live V62 regression failed"

step "8) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V62 state"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED V62 ---"; echo "$PROJECTED"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "live V62 snapshot differs from projected state"
}

step "9) SUCCESS"
echo "SUCCESS: SELF PAYEE ACCOUNT V62 DEPLOYED"
echo "SELF_PAYMENT_TOTAL=$(val "$FINAL" SELF_PAYMENT_TOTAL)"
echo "SELF_TRACKING=$(val "$FINAL" SELF_TRACKING)"
if [ "$ADD_QTY" -gt 0 ]; then
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK V59 REPAIRED"
  echo "TAKVIN_REPAIRED_QTY=$ADD_QTY"
  echo "TAKVIN_REPAIRED_VALUE=$ADD_VALUE"
else
  echo "SUCCESS: TODAY TAKVIN PURCHASE STOCK ALREADY CLEAN"
fi
echo "Backup: $BACKUP"
echo "New payment targets: tailor/fabric/elastic/takvin/self; Pedram is no longer offered."
echo "Self payment: Mellat down, حساب‌ها/خودم up as tracking, capital down by the same payment amount."
