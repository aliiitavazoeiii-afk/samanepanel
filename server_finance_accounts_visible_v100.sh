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

BASE=fae04cecc2d34a3c92c8a39052f62c36699cce0b
MIRROR_DOCKERFILE=.Dockerfile.v100.mirror.tmp
MIRROR_COMPOSE=.compose.v100.mirror.tmp.yml
cleanup(){ rm -f "$MIRROR_DOCKERFILE" "$MIRROR_COMPOSE"; }
trap cleanup EXIT INT TERM

build_web(){
  if docker compose build web; then return 0; fi
  echo "Primary Docker Hub build failed. Retrying via mirror.gcr.io ..."
  cleanup
  awk 'NR==1 { if($0!="FROM python:3.12-slim"){print "Unexpected Dockerfile base image: "$0 > "/dev/stderr"; exit 42} print "FROM mirror.gcr.io/library/python:3.12-slim"; next } {print}' Dockerfile > "$MIRROR_DOCKERFILE" || return 1
  cat > "$MIRROR_COMPOSE" <<'YAML'
services:
  web:
    build:
      context: .
      dockerfile: .Dockerfile.v100.mirror.tmp
YAML
  docker compose -f compose.yml -f "$MIRROR_COMPOSE" build web || return 1
  cleanup
}

snapshot_code(){
cat <<'PY'
from hashlib import sha256
from core.models import (
    AccountEntry, AppSetting, BusinessPayment, DigikalaSettlement, ExcelManualRow,
    ExcelManualSetting, InventoryMovement, MaterialReportConsumption,
    MaterialReportOutputApplied, RawMaterialStock, SaleLine, SaleSnapshot, StockBalance,
)

def digest(model):
    fields=[f.attname for f in model._meta.concrete_fields]
    h=sha256()
    for row in model.objects.order_by(model._meta.pk.attname).values_list(*fields):
        h.update(repr(tuple(row)).encode('utf-8')); h.update(b'\n')
    return h.hexdigest()

for label,model in [
    ('RAW_HASH',RawMaterialStock),('MATERIAL_CONSUMPTION_HASH',MaterialReportConsumption),
    ('MATERIAL_OUTPUT_HASH',MaterialReportOutputApplied),('STOCK_HASH',StockBalance),
    ('MOVEMENT_HASH',InventoryMovement),('SALELINE_HASH',SaleLine),('SNAPSHOT_HASH',SaleSnapshot),
    ('ACCOUNTENTRY_HASH',AccountEntry),('APPSETTINGS_HASH',AppSetting),
    ('MANUAL_SETTINGS_HASH',ExcelManualSetting),('MANUAL_ROWS_HASH',ExcelManualRow),
    ('PAYMENTS_HASH',BusinessPayment),('RECEIPTS_HASH',DigikalaSettlement),
]:
    print('%s=%s' % (label,digest(model)))
PY
}

snapshot_exec(){ CODE=$(snapshot_code); docker compose exec -T web python manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|PAYMENTS_HASH|RECEIPTS_HASH)='; }
snapshot_run(){ CODE=$(snapshot_code); docker compose run --rm --entrypoint python web manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(RAW_HASH|MATERIAL_CONSUMPTION_HASH|MATERIAL_OUTPUT_HASH|STOCK_HASH|MOVEMENT_HASH|SALELINE_HASH|SNAPSHOT_HASH|ACCOUNTENTRY_HASH|APPSETTINGS_HASH|MANUAL_SETTINGS_HASH|MANUAL_ROWS_HASH|PAYMENTS_HASH|RECEIPTS_HASH)='; }

step "1) BACKUP + PRE STATE"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
docker compose ps --status running web | grep -q 'web' || fail "live web container not running"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-finance-accounts-visible-v100-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "pre snapshot failed"
echo "$PRE"

step "2) VERIFY V100 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V99 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|core/finance_center_v97.py|templates/core/finance_center_v97.html|core/ui_polish_v98.py|core/management/commands/check_finance_nav_polish_v98.py|docs/PROJECT_CONTEXT/51_FINANCE_ACCOUNTS_VISIBLE_V100.md|server_finance_accounts_visible_v100.sh) ;;
    *) fail "unexpected V100 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/material_flow.py core/report_v10.py \
  core/business_tools_v91.py core/business_tools_v62.py core/business_receipts_v64.py \
  core/calculator_v37.py core/finance.py core/cost_accounting_v14.py core/sale_price_v60.py \
  core/inventory_center_v97.py templates/core/finance_accounts_v97.html \
  || fail "protected business/accounting source changed"

step "3) BUILD + REGRESSIONS"
build_web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django system check failed"
docker compose run --rm --entrypoint python web manage.py check_global_calendar_inventory_v94 || fail "V94 regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_finance_center_v97 || fail "V97 regression failed"
docker compose run --rm --entrypoint python web manage.py check_finance_nav_polish_v98 || fail "V100 finance account visibility regression failed"

step "4) PROJECTED STATE"
PROJECTED=$(snapshot_run) || fail "projected snapshot failed"
echo "$PROJECTED"
[ "$PRE" = "$PROJECTED" ] || { echo "--- PRE ---"; echo "$PRE"; echo "--- PROJECTED ---"; echo "$PROJECTED"; fail "V100 image changed business state"; }

step "5) RECREATE LIVE WEB"
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_material_finance_center_v97 || fail "live V97 regression failed"
docker compose exec -T web python manage.py check_finance_nav_polish_v98 || fail "live V100 regression failed"

step "6) FINAL STATE"
FINAL=$(snapshot_exec) || fail "final snapshot failed"
echo "$FINAL"
[ "$PRE" = "$FINAL" ] || { echo "--- PRE ---"; echo "$PRE"; echo "--- FINAL ---"; echo "$FINAL"; fail "V100 deployment changed business state"; }

step "7) SUCCESS"
echo "SUCCESS: FINANCE ACCOUNTS VISIBLE V100 DEPLOYED"
echo "Finance hub: 3 requested cards + live current account balances"
echo "Full accounts page: same canonical ExcelManualRow account/person sources"
echo "ERP HTML: no-cache to prevent stale Finance page"
echo "No account migration/copy and no business-state rewrite"
echo "Backup: $BACKUP"
