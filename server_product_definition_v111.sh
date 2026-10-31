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

BASE=82b88bc95f3de3f71027c08f94a047b77b6ac4b8
MIRROR_DOCKERFILE=.Dockerfile.v111.mirror.tmp
MIRROR_COMPOSE=.compose.v111.mirror.tmp.yml
cleanup(){ rm -f "$MIRROR_DOCKERFILE" "$MIRROR_COMPOSE"; }
trap cleanup EXIT INT TERM

build_web(){
  if docker compose build web; then return 0; fi
  echo "Primary build failed. Retrying via mirror.gcr.io ..."
  awk 'NR==1 { if($0!="FROM python:3.12-slim"){exit 42} print "FROM mirror.gcr.io/library/python:3.12-slim"; next } {print}' Dockerfile > "$MIRROR_DOCKERFILE" || return 1
  cat > "$MIRROR_COMPOSE" <<'YAML'
services:
  web:
    build:
      context: .
      dockerfile: .Dockerfile.v111.mirror.tmp
YAML
  docker compose -f compose.yml -f "$MIRROR_COMPOSE" build web
}

snapshot_code(){
cat <<'PY'
from hashlib import sha256
from core.models import (
    AccountEntry, AppSetting, BusinessPayment, DigikalaSettlement,
    ExcelManualRow, ExcelManualSetting, InventoryMovement,
    MaterialReportBlock, MaterialReportConsumption, MaterialReportOutputApplied,
    ProductCode, ProductSize, RawMaterialStock, SaleLine, SaleSnapshot,
    StockBalance, TakvinCostRule,
)
def digest(model):
    # Cross-schema snapshots use old canonical ProductCode fields only.
    # V111 adds a blank title column; it is intentionally not a business rewrite.
    fields=(["id","brand_id","code","pack_qty","active","note"]
            if model is ProductCode else [f.attname for f in model._meta.concrete_fields])
    h=sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode("utf-8")); h.update(b"\n")
    return h.hexdigest()
for label,model in [
    ("RAW_HASH",RawMaterialStock),
    ("MATERIAL_BLOCK_HASH",MaterialReportBlock),
    ("MATERIAL_CONSUMPTION_HASH",MaterialReportConsumption),
    ("MATERIAL_OUTPUT_HASH",MaterialReportOutputApplied),
    ("STOCK_HASH",StockBalance),
    ("MOVEMENT_HASH",InventoryMovement),
    ("SALELINE_HASH",SaleLine),
    ("SNAPSHOT_HASH",SaleSnapshot),
    ("ACCOUNTENTRY_HASH",AccountEntry),
    ("APPSETTINGS_HASH",AppSetting),
    ("MANUAL_SETTINGS_HASH",ExcelManualSetting),
    ("MANUAL_ROWS_HASH",ExcelManualRow),
    ("PAYMENTS_HASH",BusinessPayment),
    ("RECEIPTS_HASH",DigikalaSettlement),
    ("PRODUCT_CODE_HASH",ProductCode),
    ("PRODUCT_SIZE_HASH",ProductSize),
    ("TAKVIN_COST_RULE_HASH",TakvinCostRule),
]:
    print("%s=%s" % (label,digest(model)))
PY
}

snapshot_exec(){
  CODE=$(snapshot_code)
  docker compose exec -T web python manage.py shell -c "$CODE" 2>/dev/null |
    grep -E '^(RAW_HASH|MATERIAL_BLOCK_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|PAYMENTS_HASH|RECEIPTS_HASH|PRODUCT_CODE_HASH|PRODUCT_SIZE_HASH|TAKVIN_COST_RULE_HASH)='
}
snapshot_run(){
  CODE=$(snapshot_code)
  docker compose run --rm --entrypoint python web manage.py shell -c "$CODE" 2>/dev/null |
    grep -E '^(RAW_HASH|MATERIAL_BLOCK_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|PAYMENTS_HASH|RECEIPTS_HASH|PRODUCT_CODE_HASH|PRODUCT_SIZE_HASH|TAKVIN_COST_RULE_HASH)='
}

step "1) BACKUP + PRE STATE"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "db start failed"
docker compose ps --status running web | grep -q 'web' || fail "live web not running"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-product-definition-v111-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "pre snapshot failed"
echo "$PRE"

step "2) VERIFY PRODUCT-DEFINITION SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V110 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|\
    core/models.py|\
    core/migrations/0018_productcode_title.py|\
    core/settings_product_v60.py|\
    core/anbaresh_catalog_v19.py|\
    core/product_center_v93.py|\
    core/sale_entry_v60.py|\
    core/management/commands/check_product_definition_v111.py|\
    templates/core/settings_product_form.html|\
    templates/core/settings_products_v93.html|\
    templates/core/_product_center_colors_v93.html|\
    templates/core/sale_size.html|\
    docs/PROJECT_CONTEXT/60_PRODUCT_DEFINITION_V111.md|\
    docs/PROJECT_CONTEXT/README.md|\
    server_product_definition_v111.sh) ;;
    *) fail "unexpected V111 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD --   core/models_final.py core/finance.py   core/report_v10.py core/capital_history_v87.py   core/business_tools_v62.py core/business_tools_v91.py   core/business_receipts_v64.py core/payment_source_v63.py   core/finance_center_v97.py core/calculator_v37.py core/material_report_v92.py   core/material_report_v23.py core/material_flow.py   core/inventory_v20.py core/inventory_operations_v15.py   core/inventory_operations_v16.py core/inventory_operations_v17.py   core/darma_cost_v55.py core/novani_cost_v59.py   core/takvin_pricing_v17.py core/sale_price_v60.py   || fail "protected business/accounting/material source changed"

step "3) BUILD + ADDITIVE MIGRATION"
build_web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose exec -T web python manage.py showmigrations core | grep -Fq "[X] 0017_digikalasettlement_source" || fail "core migration 0017 is not yet applied; stop for manual audit"
docker compose run --rm --entrypoint python web manage.py migrate core 0018_productcode_title --noinput || fail "additive ProductCode title migration failed"

step "3B) FULL REGRESSIONS BEFORE LIVE SWITCH"
docker compose run --rm --entrypoint python web manage.py check_final_baseline_v108 || fail "V108 stable baseline regression failed"
docker compose run --rm --entrypoint python web manage.py check_margin_material_v105 || fail "V105 material/calculator regression failed"
docker compose run --rm --entrypoint python web manage.py check_person_payments_three_delivery_v106 || fail "V106 person/delivery regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110 compact material regression failed"
docker compose run --rm --entrypoint python web manage.py check_product_pricing_center_v93 || fail "V93 product/pricing regression failed"
docker compose run --rm --entrypoint python web manage.py check_product_definition_v111 || fail "V111 product/catalog/sales regression failed"

step "4) PROJECTED STATE"
PROJECTED=$(snapshot_run) || fail "projected snapshot failed"
echo "$PROJECTED"
[ "$PRE" = "$PROJECTED" ] || {
  echo "--- PRE ---"; echo "$PRE"
  echo "--- PROJECTED ---"; echo "$PROJECTED"
  fail "V111 image changed business state"
}

step "5) RECREATE LIVE WEB"
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_final_baseline_v108 || fail "live V108 baseline regression failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110 summary-grid regression failed"
docker compose exec -T web python manage.py check_product_pricing_center_v93 || fail "live V93 product pricing regression failed"
docker compose exec -T web python manage.py check_product_definition_v111 || fail "live V111 definition regression failed"

step "6) FINAL STATE"
FINAL=$(snapshot_exec) || fail "final snapshot failed"
echo "$FINAL"
[ "$PRE" = "$FINAL" ] || {
  echo "--- PRE ---"; echo "$PRE"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "V111 deployment changed business state"
}

step "7) SUCCESS"
echo "SUCCESS: PRODUCT DEFINITION + COLORS + DAILY SALES V111 DEPLOYED"
echo "New Product Definition card and independent product title: enabled"
echo "Canonical ProductCode + ProductComposition + ProductSize: shared by Colors and Daily Sales"
echo "Anbaresh product title mirror: preserved"
echo "Historical sale prices, stock, material/accounting formulas: unchanged"
echo "Additive database migration: core 0018_productcode_title"
echo "V108/V110 baselines and V93 pricing: verified"
echo "Existing business fields: PRE = PROJECTED = FINAL"
echo "Backup: $BACKUP"
