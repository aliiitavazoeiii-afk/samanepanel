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

BASE=dd071fb9d5b9411421268146f93ba61441778055
MIRROR_DOCKERFILE=.Dockerfile.v96.mirror.tmp
MIRROR_COMPOSE=.compose.v96.mirror.tmp.yml

cleanup_tmp_build_files() {
  rm -f "$MIRROR_DOCKERFILE" "$MIRROR_COMPOSE"
}
trap cleanup_tmp_build_files EXIT INT TERM

build_web_image() {
  if docker compose build web; then
    return 0
  fi

  echo ""
  echo "Primary Docker Hub build failed. Retrying same Dockerfile via mirror.gcr.io ..."
  cleanup_tmp_build_files

  awk '
    NR == 1 {
      if ($0 != "FROM python:3.12-slim") {
        print "Unexpected Dockerfile base image: " $0 > "/dev/stderr"
        exit 42
      }
      print "FROM mirror.gcr.io/library/python:3.12-slim"
      next
    }
    { print }
  ' Dockerfile > "$MIRROR_DOCKERFILE" || return 1

  cat > "$MIRROR_COMPOSE" <<'YAML'
services:
  web:
    build:
      context: .
      dockerfile: .Dockerfile.v96.mirror.tmp
YAML

  docker compose -f compose.yml -f "$MIRROR_COMPOSE" build web || return 1
  echo "Mirror build succeeded; image contents are otherwise identical to the project Dockerfile."
  cleanup_tmp_build_files
  return 0
}

snapshot_code() {
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
    RawMaterialStock, SaleLine, SaleSnapshot, StockBalance, TakvinCostRule,
    TakvinPurchase,
)
from core.report_v5 import _raw_material_context

def norm(s):
    return str(s or "").replace(" ","").replace("ي","ی").replace("ك","ک")
def row_balance(needle):
    for r in ExcelManualRow.objects.filter(active=True,section=ExcelManualRow.ACCOUNTS).order_by("sort_order","id"):
        if needle in norm(r.title):
            return int(r.amount or 0)
    return 0
def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
def digest_model(model):
    fields=[field.attname for field in model._meta.concrete_fields]
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
raw_ctx=_raw_material_context()
raw=int(raw_ctx["materials_total"])
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
print("RAW_HASH=%s" % digest_model(RawMaterialStock))
print("MATERIAL_CONSUMPTION_HASH=%s" % digest_model(MaterialReportConsumption))
print("MATERIAL_OUTPUT_HASH=%s" % digest_model(MaterialReportOutputApplied))
print("STOCK_HASH=%s" % digest_model(StockBalance))
print("MOVEMENT_HASH=%s" % digest_model(InventoryMovement))
print("APPSETTINGS_HASH=%s" % digest_model(AppSetting))
print("MANUAL_ROWS_HASH=%s" % digest_model(ExcelManualRow))
print("TAKVIN_COST_HASH=%s" % digest_model(TakvinCostRule))
print("PRODUCT_HASH=%s" % digest_model(ProductCode))
print("PRODUCT_SIZE_HASH=%s" % digest_model(ProductSize))
print("COMPOSITION_HASH=%s" % digest_model(ProductComposition))
print("SALELINE_HASH=%s" % digest_model(SaleLine))
print("SNAPSHOT_HASH=%s" % digest_model(SaleSnapshot))
print("ACCOUNTENTRY_HASH=%s" % digest_model(AccountEntry))
PY
}

snapshot_exec() {
  CODE=$(snapshot_code)
  docker compose exec -T web python manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|FABRIC|ELASTIC|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|APPSETTINGS_HASH|MANUAL_ROWS_HASH|TAKVIN_COST_HASH|PRODUCT_HASH|PRODUCT_SIZE_HASH|COMPOSITION_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH)='
}

snapshot_run() {
  CODE=$(snapshot_code)
  docker compose run --rm --entrypoint python web manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|FABRIC|ELASTIC|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|APPSETTINGS_HASH|MANUAL_ROWS_HASH|TAKVIN_COST_HASH|PRODUCT_HASH|PRODUCT_SIZE_HASH|COMPOSITION_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH)='
}

step "1) DATABASE BACKUP + CURRENT LIVE SNAPSHOT"
docker compose config -q || fail "compose invalid"
# Never recreate/start web before regressions: a previous failed deploy may have
# built a newer local image while the old live container is still the safe source.
docker compose up -d db || fail "database start failed"
docker compose ps --status running web | grep -q 'web' || fail "live web container is not running"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1
  i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-inventory-material-center-v96-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "could not capture pre-V96 live state"
echo "$PRE"

step "2) VERIFY V96 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V95 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|core/inventory_center_v96.py|core/urls.py|core/inventory_v20.py|core/report_v10.py|core/management/commands/check_inventory_material_center_v96.py|templates/core/inventory_center_v96.html|templates/core/raw_material_inventory_v96.html|templates/core/report_excel_v96.html|docs/PROJECT_CONTEXT/48_INVENTORY_MATERIAL_CENTER_V96.md|server_inventory_material_center_v96.sh) ;;
    *) fail "unexpected V96 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/material_flow.py core/report_v5.py \
  core/inventory_valuation_v17.py core/final_services.py \
  core/material_report_v20.py core/material_report_v21.py core/material_report_v22.py \
  core/material_report_v23.py core/material_report_v92.py \
  core/finance.py core/cost_accounting_v14.py core/daily_order_import_v23.py \
  core/daily_order_views_v60.py core/sale_price_v60.py core/sale_entry_v60.py \
  core/business_tools_v62.py core/business_receipts_v64.py core/payment_source_v63.py \
  core/darma_cost_v55.py core/novani_cost_v59.py core/takvin_pricing_v17.py \
  core/product_center_v93.py core/pricing_v60.py \
  || fail "protected material/inventory/sales/accounting source changed"

step "3) BUILD + READ-ONLY REGRESSIONS"
build_web_image || fail "web build failed on Docker Hub and mirror.gcr.io"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django system check failed"
docker compose run --rm --entrypoint python web manage.py check_cost_rules_takvin_purchase_v59 || fail "V59 cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_transfer_adjust_guard_v80 || fail "V80 inventory guard regression failed"
docker compose run --rm --entrypoint python web manage.py check_pricing_monitor_v89 || fail "V89 pricing monitor regression failed"
docker compose run --rm --entrypoint python web manage.py check_daily_color_size_v90 || fail "V90 daily matrix regression failed"
docker compose run --rm --entrypoint python web manage.py check_receipt_filters_v91 || fail "V91 receipt regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_month_archive_v92 || fail "V92 material-report regression failed"
docker compose run --rm --entrypoint python web manage.py check_product_pricing_center_v93 || fail "V93 pricing-center regression failed"
docker compose run --rm --entrypoint python web manage.py check_global_calendar_inventory_v94 || fail "V94 global-calendar regression failed"
docker compose run --rm --entrypoint python web manage.py check_multi_delivery_mehr8_v95 || fail "V95 multi-delivery regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_material_center_v96 || fail "V96 inventory/material regression failed"

step "4) VERIFY NEW IMAGE IS STATE NEUTRAL BEFORE LIVE RECREATE"
PROJECTED=$(snapshot_run) || fail "could not capture V96 projected state"
echo "$PROJECTED"
[ "$PRE" = "$PROJECTED" ] || {
  echo "--- PRE V96 ---"; echo "$PRE"
  echo "--- PROJECTED V96 ---"; echo "$PROJECTED"
  fail "V96 new image changed business/material/inventory state before live recreate"
}

step "5) RECREATE LIVE WEB"
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_product_pricing_center_v93 || fail "live V93 pricing regression failed"
docker compose exec -T web python manage.py check_global_calendar_inventory_v94 || fail "live V94 regression failed"
docker compose exec -T web python manage.py check_multi_delivery_mehr8_v95 || fail "live V95 regression failed"
docker compose exec -T web python manage.py check_inventory_material_center_v96 || fail "live V96 regression failed"

step "6) FINAL STATE INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V96 state"
echo "$FINAL"
[ "$PRE" = "$FINAL" ] || {
  echo "--- PRE V96 ---"; echo "$PRE"
  echo "--- FINAL V96 ---"; echo "$FINAL"
  fail "V96 deployment changed business/material/inventory state"
}

step "7) SUCCESS"
echo "SUCCESS: INVENTORY + MATERIAL CENTER V96 DEPLOYED"
echo "Inventory hub: finished goods + raw materials"
echo "Raw-material source/formulas: unchanged"
echo "Same-color fabric lots: aggregated for display only; provenance preserved"
echo "Comprehensive report: inventory/material detail UI moved out; capital math unchanged"
echo "V95 multi-file + Mehr 8 commission exception regression-checked"
echo "Backup: $BACKUP"
