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

BASE=3d0a996633d944b87539de796f281dbe83d97f85
MIRROR_DOCKERFILE=.Dockerfile.v92.mirror.tmp
MIRROR_COMPOSE=.compose.v92.mirror.tmp.yml

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
      dockerfile: .Dockerfile.v92.mirror.tmp
YAML

  docker compose -f compose.yml -f "$MIRROR_COMPOSE" build web || return 1
  echo "Mirror build succeeded; image contents are otherwise identical to the project Dockerfile."
  cleanup_tmp_build_files
  return 0
}

snapshot_code() {
cat <<'PY'
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand,BusinessPayment,DigikalaSettlement,ExcelManualRow,ExcelManualSetting,InventoryMovement,MaterialReportBlock,MaterialReportConsumption,MaterialReportOutputApplied,RawMaterialStock,SaleLine,StockBalance,TakvinPurchase
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
print("MATERIAL_BLOCKS=%d" % MaterialReportBlock.objects.count())
print("MATERIAL_OUTPUTS=%d" % MaterialReportOutputApplied.objects.count())
print("MATERIAL_CONSUMPTIONS=%d" % MaterialReportConsumption.objects.count())
PY
}

snapshot_exec() {
  CODE=$(snapshot_code)
  docker compose exec -T web python manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|MATERIAL_BLOCKS|MATERIAL_OUTPUTS|MATERIAL_CONSUMPTIONS)='
}

snapshot_run() {
  CODE=$(snapshot_code)
  docker compose run --rm --entrypoint python web manage.py shell -c "$CODE" 2>/dev/null | grep -E '^(CAPITAL|MELLAT|MOFID|FINISHED|RAW|DIGI|DIA|TAKVIN_DEBT|DARMA_QTY|TAKVIN_QTY|NOVANI_QTY|SALES|PAYMENTS|RECEIPTS|RAW_ROWS|MOVEMENTS|TAKVIN_PURCHASES|MATERIAL_BLOCKS|MATERIAL_OUTPUTS|MATERIAL_CONSUMPTIONS)='
}

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
BACKUP="backups/before-material-month-archive-v92-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
PRE=$(snapshot_exec) || fail "could not capture pre-V92 live state"
echo "$PRE"

step "2) VERIFY V92 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V91 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|core/material_report_v92.py|core/management/commands/check_material_month_archive_v92.py|core/urls.py|docs/PROJECT_CONTEXT/44_MATERIAL_MONTH_ARCHIVE_V92.md|templates/core/material_report_v92.html|server_material_month_archive_v92.sh) ;;
    *) fail "unexpected V92 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/finance.py core/cost_accounting_v14.py \
  core/final_services.py core/inventory_valuation_v17.py core/report_v10.py \
  core/darma_cost_v55.py core/novani_cost_v59.py core/takvin_pricing_v17.py \
  core/sale_price_v60.py core/daily_order_import_v23.py core/daily_order_views_v60.py \
  core/business_tools_v62.py core/business_receipts_v64.py core/payment_source_v63.py \
  core/material_report_v20.py core/material_report_v21.py core/material_report_v22.py core/material_report_v23.py \
  || fail "protected business/accounting/material mutation source changed"

step "3) BUILD + READ-ONLY REGRESSIONS"
build_web_image || fail "web build failed on Docker Hub and mirror.gcr.io"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django system check failed"
docker compose run --rm --entrypoint python web manage.py check_daily_color_size_v90 || fail "V90 regression failed"
docker compose run --rm --entrypoint python web manage.py check_receipt_filters_v91 || fail "V91 regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_month_archive_v92 || fail "V92 regression failed"

step "4) VERIFY NEW IMAGE IS BUSINESS-STATE NEUTRAL"
PROJECTED=$(snapshot_run) || fail "could not capture V92 projected state"
echo "$PROJECTED"
[ "$PRE" = "$PROJECTED" ] || {
  echo "--- PRE V92 ---"; echo "$PRE"
  echo "--- PROJECTED V92 ---"; echo "$PROJECTED"
  fail "V92 new image changed business state before live recreate"
}

step "5) RECREATE LIVE WEB"
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_receipt_filters_v91 || fail "live V91 regression failed"
docker compose exec -T web python manage.py check_material_month_archive_v92 || fail "live V92 regression failed"

step "6) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_exec) || fail "could not capture final V92 state"
echo "$FINAL"
[ "$PRE" = "$FINAL" ] || {
  echo "--- PRE V92 ---"; echo "$PRE"
  echo "--- FINAL V92 ---"; echo "$FINAL"
  fail "V92 changed business/accounting/inventory/material state"
}

step "7) SUCCESS"
echo "SUCCESS: MATERIAL MONTH ARCHIVE V92 DEPLOYED"
echo "Material report: past Jalali months collapsed to one expandable row"
echo "Current month KPIs: rolls, kg, minimum delivery, applied delivered, pending"
echo "V91 receipt filters included and regression-checked"
echo "Backup: $BACKUP"
