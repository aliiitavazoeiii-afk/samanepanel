#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=ecefa162d732c841c6788f633cbe5f9f6cab2884

snapshot_exec() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,DigikalaSettlement,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def norm(s):
    return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title): return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS).exclude(note__startswith="[system:self-spend-v62]"))
persons=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.PERSONS))
dia=int(dia_gallery_receivable_total())
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+persons+dia+assets+finished+raw+digi-debt

print("CAPITAL=%d" % capital)
print("MELLAT=%d" % row_balance("ملت"))
print("MOFID=%d" % row_balance("مفید"))
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
print("RECEIPTS=%d" % DigikalaSettlement.objects.count())
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

snapshot_run() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,DigikalaSettlement,ExcelManualRow,ExcelManualSetting,InventoryMovement,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
from core.report_v5 import _raw_material_context

def norm(s):
    return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title): return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS).exclude(note__startswith="[system:self-spend-v62]"))
persons=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.PERSONS))
dia=int(dia_gallery_receivable_total())
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+persons+dia+assets+finished+raw+digi-debt

print("CAPITAL=%d" % capital)
print("MELLAT=%d" % row_balance("ملت"))
print("MOFID=%d" % row_balance("مفید"))
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
print("RECEIPTS=%d" % DigikalaSettlement.objects.count())
print("RAW_ROWS=%d" % RawMaterialStock.objects.count())
print("MOVEMENTS=%d" % InventoryMovement.objects.count())
print("TAKVIN_PURCHASES=%d" % TakvinPurchase.objects.count())
' 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES)='
}

step "1) DATABASE BACKUP + CURRENT LIVE SNAPSHOT"
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
BACKUP="backups/before-multi-receipts-v64-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "could not capture current live state"
echo "$PRE"

step "2) VERIFY V64 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V64 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/models_final.py|core/migrations/0017_digikalasettlement_source.py|core/business_receipts_v64.py|core/business_tools_v62.py|core/urls.py|templates/core/payments_v22.html|core/static/core/payments_source_v63.js|core/management/commands/check_multi_receipts_v64.py|server_multi_receipts_v64.sh) ;;
    *) fail "unexpected V64 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD --   core/report_v10.py core/self_spend_v62.py core/business_tools_v60.py   core/material_purchase_v60.py core/sale_price_v60.py core/darma_cost_v55.py   core/novani_cost_v59.py core/inventory_valuation_v17.py core/takvin_v5.py   core/finance.py core/cost_accounting_v14.py core/final_services.py   || fail "protected business source changed"

step "3) BUILD + MIGRATE"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check before migrate failed"
docker compose run --rm --entrypoint python web manage.py migrate --plan || fail "migration plan failed"
docker compose run --rm --entrypoint python web manage.py migrate --noinput || fail "migration failed"

POST_MIGRATE=$(snapshot_run) || fail "could not capture post-migration state"
echo "$POST_MIGRATE"
[ "$PRE" = "$POST_MIGRATE" ] || {
  echo "--- BEFORE MIGRATION ---"; echo "$PRE"
  echo "--- AFTER MIGRATION ---"; echo "$POST_MIGRATE"
  fail "receipt source migration changed business values"
}

docker compose run --rm --entrypoint python web manage.py shell -c '
from core.models import DigikalaSettlement
bad=DigikalaSettlement.objects.exclude(source__in=["digikala","dia_gallery"]).count()
legacy=DigikalaSettlement.objects.filter(source="digikala").count()
print("INVALID_RECEIPT_SOURCE_ROWS=%d" % bad)
print("DIGIKALA_RECEIPT_ROWS=%d" % legacy)
assert bad == 0
' || fail "receipt source migration verification failed"

step "4) REGRESSIONS"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 regression failed"
docker compose run --rm --entrypoint python web manage.py check_sale_price_elastic_multi_v60 || fail "V60 regression failed"
docker compose run --rm --entrypoint python web manage.py check_self_payee_account_v62 || fail "V62 regression failed"
docker compose run --rm --entrypoint python web manage.py check_payment_source_v63 || fail "V63 payment-source regression failed"
docker compose run --rm --entrypoint python web manage.py check_multi_receipts_v64 || fail "V64 receipt regression failed"

step "5) CARRY FORWARD SAFE REPAIRS"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 || fail "V59 Takvin repair dry-run failed"
docker compose run --rm --entrypoint python web manage.py repair_takvin_purchase_stock_v59 --apply || fail "V59 Takvin repair apply failed"
docker compose run --rm --entrypoint python web manage.py repair_self_tracking_v62 || fail "V62 self tracking dry-run failed"
docker compose run --rm --entrypoint python web manage.py repair_self_tracking_v62 --apply || fail "V62 self tracking reconcile failed"

step "6) PROJECT NEW LIVE STATE"
PROJECTED=$(snapshot_run) || fail "could not capture projected V64 state"
echo "$PROJECTED"

step "7) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_payment_source_v63 || fail "live V63 payment-source regression failed"
docker compose exec -T web python manage.py check_multi_receipts_v64 || fail "live V64 receipt regression failed"

step "8) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V64 state"
echo "$FINAL"
[ "$PROJECTED" = "$FINAL" ] || {
  echo "--- PROJECTED V64 ---"; echo "$PROJECTED"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "live V64 state differs from projected state"
}

step "9) SUCCESS"
echo "SUCCESS: MULTI RECEIPTS V64 DEPLOYED"
echo "Receipts: Digikala / Dia Gallery -> Mellat"
echo "Payments: source account remains Mellat / Mofid"
echo "Backup: $BACKUP"
