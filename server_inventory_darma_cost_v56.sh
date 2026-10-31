#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=f355c243f3c63f976bf82c8744971acad972bb7d

snapshot_business() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryMovement, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer
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
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|DIA_SALES|SALE_SNAPSHOTS|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS)='
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
BACKUP="backups/before-darma-inventory-page-cost-v56-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"
sleep 2
LIVE=$(snapshot_business) || fail "could not capture live business snapshot"
echo "$LIVE"

step "2) VERIFY V56 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V56 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/inventory_v20.py|templates/core/inventory_v19.html|core/management/commands/check_inventory_darma_cost_v56.py|server_inventory_darma_cost_v56.sh|docs/PROJECT_CONTEXT/34_DARMA_INVENTORY_PAGE_COST_V56.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V56 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/darma_cost_v55.py core/cost_accounting_v14.py core/inventory_valuation_v17.py \
  core/dia_gallery_v45.py core/finance.py core/final_services.py core/settings_rules_v17.py \
  core/darma_pricing.py core/models.py core/models_final.py core/migrations core/urls.py \
  core/returns_v37.py core/finance_excel_v9.py core/report_v9.py core/daily_report_v8.py \
  core/daily_order_import_v23.py core/daily_order_views_v8.py core/variant_sale_v12.py \
  || fail "protected accounting/sales source changed in V56"

step "3) BUILD + READ-ONLY REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_darma_cost_v56 || fail "V56 Darma inventory page regression failed"

step "4) VERIFY PREFLIGHT CHANGED NO BUSINESS DATA"
PREFLIGHT=$(snapshot_business) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- AFTER PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "V56 preflight changed persistent business data"
}

step "5) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_darma_cost_rule_v55 || fail "live V55 regression failed"
docker compose exec -T web python manage.py check_inventory_darma_cost_v56 || fail "live V56 regression failed"

step "6) VERIFY LIVE DARMA PAGE VALUE + INVARIANTS"
docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.darma_cost_v55 import darma_cost_for
from core.models import Brand, StockBalance
b=Brand.objects.get(name="دارما")
q=int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
c=int(darma_cost_for())
print(f"EXPECTED_DARMA_PAGE_QTY={q}")
print(f"EXPECTED_DARMA_PAGE_UNIT_COST={c}")
print(f"EXPECTED_DARMA_PAGE_VALUE={q*c}")
' || fail "could not verify live Darma page value"

FINAL=$(snapshot_business) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE ---"; echo "$LIVE"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "V56 changed business data; expected presentation/service-path fix only"
}

step "7) SUCCESS"
echo "SUCCESS: DARMA INVENTORY PAGE COST V56 DEPLOYED"
echo "Backup: $BACKUP"
echo "Darma inventory page now uses the same central cost as V55 capital accounting."
