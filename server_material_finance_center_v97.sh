#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a
export COMPOSE_IGNORE_ORPHANS=1

BASE=7b1826d66bfd834f4b0456e1b20f0d505715bf89
MIRROR_DOCKERFILE=.Dockerfile.v97.mirror.tmp
MIRROR_COMPOSE=.compose.v97.mirror.tmp.yml

cleanup_tmp_build_files(){ rm -f "$MIRROR_DOCKERFILE" "$MIRROR_COMPOSE"; }
trap cleanup_tmp_build_files EXIT INT TERM

build_web_image(){
  if docker compose build web; then return 0; fi
  echo "Primary Docker Hub build failed. Retrying via mirror.gcr.io ..."
  cleanup_tmp_build_files
  awk 'NR==1 { if($0!="FROM python:3.12-slim"){print "Unexpected Dockerfile base image: "$0 > "/dev/stderr"; exit 42} print "FROM mirror.gcr.io/library/python:3.12-slim"; next } {print}' Dockerfile > "$MIRROR_DOCKERFILE" || return 1
  cat > "$MIRROR_COMPOSE" <<'YAML'
services:
  web:
    build:
      context: .
      dockerfile: .Dockerfile.v97.mirror.tmp
YAML
  docker compose -f compose.yml -f "$MIRROR_COMPOSE" build web || return 1
  cleanup_tmp_build_files
}

snapshot_code(){
cat <<'PY'
from hashlib import sha256
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import (
    AccountEntry, AppSetting, Brand, BusinessPayment, DigikalaSettlement,
    ExcelManualRow, ExcelManualSetting, InventoryMovement, MaterialReportConsumption,
    MaterialReportOutputApplied, ProductCode, ProductComposition, ProductSize,
    RawMaterialStock, SaleLine, SaleSnapshot, StockBalance, TakvinCostRule, TakvinPurchase,
)
from core.report_v5 import _raw_material_context

def norm(s): return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title): return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
def digest_model(model):
    fields=[f.attname for f in model._meta.concrete_fields]
    h=sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8")); h.update(b"\n")
    return h.hexdigest()

rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ACCOUNTS).exclude(note__startswith="[system:self-spend-v62]"))
persons=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.PERSONS))
dia=int(dia_gallery_receivable_total())
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw_ctx=_raw_material_context(); raw=int(raw_ctx["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+persons+dia+assets+finished+raw+digi-debt

print("CAPITAL=%d" % capital)
print("MELLAT=%d" % row_balance("ملت"))
print("MOFID=%d" % row_balance("مفید"))
print("FINISHED=%d" % finished)
print("RAW=%d" % raw)
print("FABRIC=%d" % int(raw_ctx["fabric_total"]))
print("ELASTIC=%d" % int(raw_ctx["elastic_total"]))
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
for label,model in [
 ("RAW_HASH",RawMaterialStock),("MATERIAL_CONSUMPTION_HASH",MaterialReportConsumption),
 ("MATERIAL_OUTPUT_HASH",MaterialReportOutputApplied),("STOCK_HASH",StockBalance),
 ("MOVEMENT_HASH",InventoryMovement),("APPSETTINGS_HASH",AppSetting),
 ("MANUAL_SETTINGS_HASH",ExcelManualSetting),("MANUAL_ROWS_HASH",ExcelManualRow),
 ("TAKVIN_COST_HASH",TakvinCostRule),("PRODUCT_HASH",ProductCode),
 ("PRODUCT_SIZE_HASH",ProductSize),("COMPOSITION_HASH",ProductComposition),
 ("SALELINE_HASH",SaleLine),("SNAPSHOT_HASH",SaleSnapshot),("ACCOUNTENTRY_HASH",AccountEntry),
]: print("%s=%s" % (label,digest_model(model)))
PY
}

snapshot_exec(){ CODE=$(snapshot_code); docker compose exec -T web python manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|FABRIC|ELASTIC|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|TAKVIN_COST_HASH|PRODUCT_HASH|PRODUCT_SIZE_HASH|COMPOSITION_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH)='; }
snapshot_run(){ CODE=$(snapshot_code); docker compose run --rm --entrypoint python web manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|FABRIC|ELASTIC|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|TAKVIN_COST_HASH|PRODUCT_HASH|PRODUCT_SIZE_HASH|COMPOSITION_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH)='; }

step "1) DATABASE BACKUP + CURRENT LIVE SNAPSHOT"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
docker compose ps --status running web | grep -q 'web' || fail "live web container is not running"
i=1; while [ "$i" -le 30 ]; do docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break; [ "$i" -eq 30 ] && fail "PostgreSQL not ready"; sleep 1; i=$((i+1)); done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-material-finance-center-v97-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "could not capture pre-V97 state"
echo "$PRE"

step "2) VERIFY V97 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V96 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD); echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|core/inventory_center_v97.py|core/finance_center_v97.py|core/urls.py|core/report_v10.py|core/management/commands/check_material_finance_center_v97.py|templates/core/raw_material_inventory_v97.html|templates/core/finance_center_v97.html|templates/core/finance_accounts_v97.html|templates/core/_finance_manual_table_v97.html|templates/core/report_excel_v97.html|static/core/number_format.js|docs/PROJECT_CONTEXT/49_MATERIAL_FINANCE_CENTER_V97.md|server_material_finance_center_v97.sh) ;;
    *) fail "unexpected V97 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/models.py core/models_final.py core/material_flow.py core/report_v5.py core/inventory_valuation_v17.py core/finance.py core/cost_accounting_v14.py core/daily_order_import_v23.py core/daily_order_views_v60.py core/sale_price_v60.py core/sale_entry_v60.py core/business_tools_v62.py core/business_tools_v91.py core/business_receipts_v64.py core/payment_source_v63.py core/darma_cost_v55.py core/novani_cost_v59.py core/takvin_pricing_v17.py core/calculator_v37.py || fail "protected business/accounting/payment/calculator source changed"

step "3) BUILD + READ-ONLY REGRESSIONS"
build_web_image || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django system check failed"
docker compose run --rm --entrypoint python web manage.py check_pricing_monitor_v89 || fail "V89 regression failed"
docker compose run --rm --entrypoint python web manage.py check_daily_color_size_v90 || fail "V90 regression failed"
docker compose run --rm --entrypoint python web manage.py check_receipt_filters_v91 || fail "V91 regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_month_archive_v92 || fail "V92 regression failed"
docker compose run --rm --entrypoint python web manage.py check_product_pricing_center_v93 || fail "V93 regression failed"
docker compose run --rm --entrypoint python web manage.py check_global_calendar_inventory_v94 || fail "V94 regression failed"
docker compose run --rm --entrypoint python web manage.py check_multi_delivery_mehr8_v95 || fail "V95 regression failed"
# V96's regression asserts the old V96 route functions exactly, so V97 supersedes
# that route-level check with the V97 command below while retaining its data invariants.
docker compose run --rm --entrypoint python web manage.py check_material_finance_center_v97 || fail "V97 regression failed"

step "4) VERIFY NEW IMAGE IS STATE NEUTRAL"
PROJECTED=$(snapshot_run) || fail "could not capture projected V97 state"
echo "$PROJECTED"
[ "$PRE" = "$PROJECTED" ] || { echo "--- PRE ---"; echo "$PRE"; echo "--- PROJECTED ---"; echo "$PROJECTED"; fail "V97 image changed business state"; }

step "5) RECREATE LIVE WEB"
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_material_finance_center_v97 || fail "live V97 regression failed"

step "6) FINAL STATE INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V97 state"
echo "$FINAL"
[ "$PRE" = "$FINAL" ] || { echo "--- PRE ---"; echo "$PRE"; echo "--- FINAL ---"; echo "$FINAL"; fail "V97 deployment changed business state"; }

step "7) SUCCESS"
echo "SUCCESS: MATERIAL + FINANCE CENTER V97 DEPLOYED"
echo "Raw materials: card -> location -> clean table"
echo "Fabric internal lots: hidden from table; provenance preserved"
echo "Tailor transfer controls: restored for fabric and elastic"
echo "Finance & Tools: one nav entry with 3 cards"
echo "Accounts: moved out of comprehensive report"
echo "Payments/receipts and calculator logic: unchanged"
echo "Capital/material/accounting formulas: unchanged"
echo "Backup: $BACKUP"
