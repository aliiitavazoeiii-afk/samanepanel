#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }
getv(){ echo "$1" | sed -n "s/^$2=//p" | tail -n 1; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=f97f157f7206bcec0340789d822ca17e05888980

snapshot_business() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.dateutils import parse_jalali_date
from core.dia_gallery_v45 import dia_gallery_receivable_total
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, DiaGallerySale, ExcelManualRow, ExcelManualSetting, InventoryAdjustment, InventoryModelCost, InventoryMovement, SaleDay, SaleLine, SaleSnapshot, StockBalance, StockTransfer
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)

darma=Brand.objects.get(name="دارما")
cost_map={(r.brand_id,r.color_id,r.size_id):int(r.unit_cost or 0) for r in InventoryModelCost.objects.filter(brand=darma)}
old_darma_value=0
for r in StockBalance.objects.filter(brand=darma).values("brand_id","color_id","size_id").annotate(qty=Sum("qty")):
    old_darma_value += int(r["qty"] or 0) * int(cost_map.get((r["brand_id"],r["color_id"],r["size_id"]),0))
darma_qty=bqty("دارما")

dia=int(dia_gallery_receivable_total())
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)

target_dates=[parse_jalali_date("1405/06/12"),parse_jalali_date("1405/06/14")]
target_sales=SaleLine.objects.filter(day__date__in=target_dates,quantity__gt=0,product_size__product__brand__name__in=["دارما","انبارش"])
missing=target_sales.filter(snapshot__isnull=True).count()

print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DIA={dia}")
print(f"DARMA={darma_qty}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALE_DAYS={SaleDay.objects.count()}")
print(f"SALES={SaleLine.objects.count()}")
print(f"DIA_SALES={DiaGallerySale.objects.count()}")
print(f"SALE_SNAPSHOTS={SaleSnapshot.objects.count()}")
print(f"TARGET_MISSING_SNAPSHOTS={missing}")
print(f"TARGET_SALES={target_sales.count()}")
print(f"TARGET_DIA={DiaGallerySale.objects.filter(day__date__in=target_dates,quantity__gt=0).count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
print(f"ADJUSTMENTS={InventoryAdjustment.objects.count()}")
print(f"TRANSFERS={StockTransfer.objects.count()}")
print(f"MOVEMENTS={InventoryMovement.objects.count()}")
print(f"OLD_DARMA_MODEL_VALUE={old_darma_value}")
print(f"BASELINE_DARMA_VALUE={darma_qty*61000}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALE_DAYS|SALES|DIA_SALES|SALE_SNAPSHOTS|TARGET_MISSING_SNAPSHOTS|TARGET_SALES|TARGET_DIA|ACCOUNT_ENTRIES|ADJUSTMENTS|TRANSFERS|MOVEMENTS|OLD_DARMA_MODEL_VALUE|BASELINE_DARMA_VALUE)='
}

assert_same_field(){
  field="$1"; before="$2"; after="$3"
  b=$(getv "$before" "$field"); a=$(getv "$after" "$field")
  [ "$b" = "$a" ] || fail "$field changed unexpectedly: before=$b after=$a"
}

step "1) START DATABASE + BACKUP"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-darma-cost-rule-v55-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) CAPTURE PRE-V55 LIVE STATE"
docker compose up -d web || fail "web start failed"
sleep 3
LIVE_ALREADY_V55=0
if docker compose exec -T web python manage.py shell -c 'import core.darma_cost_v55' >/dev/null 2>&1; then LIVE_ALREADY_V55=1; fi
echo "LIVE_ALREADY_V55=$LIVE_ALREADY_V55"
LIVE=$(snapshot_business) || fail "could not capture live business snapshot"
echo "$LIVE"

OLD_FINISHED=$(getv "$LIVE" FINISHED)
OLD_CAPITAL=$(getv "$LIVE" CAPITAL)
OLD_DARMA_VALUE=$(getv "$LIVE" OLD_DARMA_MODEL_VALUE)
NEW_DARMA_VALUE=$(getv "$LIVE" BASELINE_DARMA_VALUE)
TARGET_MISSING=$(getv "$LIVE" TARGET_MISSING_SNAPSHOTS)
OLD_SNAPSHOTS=$(getv "$LIVE" SALE_SNAPSHOTS)
[ -n "$OLD_FINISHED" ] && [ -n "$OLD_CAPITAL" ] && [ -n "$OLD_DARMA_VALUE" ] && [ -n "$NEW_DARMA_VALUE" ] || fail "could not parse baseline values"

if [ "$LIVE_ALREADY_V55" -eq 1 ]; then EXPECTED_DELTA=0; else EXPECTED_DELTA=$((NEW_DARMA_VALUE - OLD_DARMA_VALUE)); fi
EXPECTED_FINISHED=$((OLD_FINISHED + EXPECTED_DELTA))
EXPECTED_CAPITAL=$((OLD_CAPITAL + EXPECTED_DELTA))
EXPECTED_SNAPSHOTS=$((OLD_SNAPSHOTS + TARGET_MISSING))
echo "EXPECTED_DARMA_REVALUATION_DELTA=$EXPECTED_DELTA"
echo "EXPECTED_FINISHED=$EXPECTED_FINISHED"
echo "EXPECTED_CAPITAL=$EXPECTED_CAPITAL"
echo "EXPECTED_SALE_SNAPSHOTS=$EXPECTED_SNAPSHOTS"

step "3) VERIFY V55 SOURCE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V55 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/darma_cost_v55.py|core/cost_accounting_v14.py|core/inventory_valuation_v17.py|core/dia_gallery_v45.py|core/finance.py|core/final_services.py|core/settings_rules_v17.py|core/darma_pricing.py|templates/core/settings_rules_v17.html|templates/core/settings_product_form.html|core/management/commands/check_darma_cost_rule_v55.py|core/management/commands/repair_darma_cost_shahrivar_v55.py|server_darma_cost_rule_v55.sh|docs/PROJECT_CONTEXT/33_DARMA_COST_RULE_V55.md|docs/PROJECT_CONTEXT/README.md) ;;
    *) fail "unexpected V55 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- \
  core/models.py core/models_final.py core/migrations \
  core/sale_inventory_v19.py core/variant_sale_v12.py core/finance_excel_v9.py \
  core/daily_order_import_v23.py core/daily_order_views_v8.py core/daily_report_v8.py \
  core/report_v9.py core/business_tools_v22.py core/material_report_v22.py core/returns_v37.py \
  core/calculator_v37.py core/inventory_operations_v15.py core/inventory_v20.py core/urls.py core/views.py \
  || fail "protected non-V55 business source changed"

step "4) BUILD + REGRESSIONS"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py collectstatic --noinput >/dev/null && python manage.py check_daily_report_runtime_v48' || fail "V48 daily-report runtime regression failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 returns regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_operations_v50 || fail "V50 inventory regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_operations_v51 || fail "V51 adjustment-delete regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_highlights_v52 || fail "V52 inventory-highlight regression failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_highlights_v53 || fail "V53 inventory-red-strength regression failed"
docker compose run --rm --entrypoint python web manage.py check_daily_sale_day_delete_v54 || fail "V54 full-day delete regression failed"
docker compose run --rm --entrypoint python web manage.py check_darma_cost_rule_v55 || fail "V55 Darma cost regression failed"
docker compose run --rm --entrypoint python web manage.py shell -c 'from core.darma_cost_v55 import darma_cost_for; from core.final_services import finished_inventory_value, inventory_unit_cost; from core.inventory_valuation_v17 import finished_inventory_value_v17; from core.models import Brand; b=Brand.objects.get(name="دارما"); assert int(inventory_unit_cost(b,None))==int(darma_cost_for()); assert int(finished_inventory_value())==int(finished_inventory_value_v17()); print("V55_LEGACY_HELPERS_CENTRALIZED=YES")' || fail "V55 legacy helper centralization regression failed"

step "5) VERIFY PREFLIGHT CHANGED NOTHING"
PREFLIGHT=$(snapshot_business) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || { echo "--- BEFORE ---"; echo "$LIVE"; echo "--- AFTER PREFLIGHT ---"; echo "$PREFLIGHT"; fail "V55 preflight changed persistent business data"; }

step "6) SEED CONFIRMED 61,000 BASELINE + DRY RUN REPAIR"
docker compose run --rm --entrypoint python web manage.py shell -c 'from core.darma_cost_v55 import ensure_darma_cost_baseline; x=ensure_darma_cost_baseline(); print(f"DARMA_BASELINE={x.key}:{x.value}")' || fail "could not seed Darma baseline"
docker compose run --rm --entrypoint python web manage.py repair_darma_cost_shahrivar_v55 || fail "V55 repair dry-run failed"

step "7) APPLY ONLY 12 + 14 SHAHRIVAR REPAIR"
docker compose run --rm --entrypoint python web manage.py repair_darma_cost_shahrivar_v55 --apply || fail "V55 targeted repair failed"

step "8) VERIFY REPAIR MOVED NO PHYSICAL/FINANCIAL LEDGERS"
POST_REPAIR=$(snapshot_business) || fail "could not capture post-repair snapshot"
echo "$POST_REPAIR"
for field in RAW DIGI DIA DARMA TAKVIN NOVANI SALE_DAYS SALES DIA_SALES ACCOUNT_ENTRIES ADJUSTMENTS TRANSFERS MOVEMENTS OLD_DARMA_MODEL_VALUE BASELINE_DARMA_VALUE; do assert_same_field "$field" "$LIVE" "$POST_REPAIR"; done
POST_SNAPSHOTS=$(getv "$POST_REPAIR" SALE_SNAPSHOTS)
[ "$POST_SNAPSHOTS" = "$EXPECTED_SNAPSHOTS" ] || fail "target repair changed unexpected SaleSnapshot count: expected=$EXPECTED_SNAPSHOTS actual=$POST_SNAPSHOTS"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 7
docker compose exec -T web python manage.py migrate --check || fail "migration check failed"
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_daily_report_runtime_v48 || fail "live V48 regression failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 returns regression failed"
docker compose exec -T web python manage.py check_daily_sale_day_delete_v54 || fail "live V54 regression failed"
docker compose exec -T web python manage.py check_darma_cost_rule_v55 || fail "live V55 regression failed"
docker compose exec -T web python manage.py shell -c 'from core.darma_cost_v55 import darma_cost_for; from core.final_services import finished_inventory_value, inventory_unit_cost; from core.inventory_valuation_v17 import finished_inventory_value_v17; from core.models import Brand; b=Brand.objects.get(name="دارما"); assert int(inventory_unit_cost(b,None))==int(darma_cost_for()); assert int(finished_inventory_value())==int(finished_inventory_value_v17()); print("LIVE_V55_LEGACY_HELPERS_CENTRALIZED=YES")' || fail "live V55 legacy helper centralization regression failed"

step "10) VERIFY 12 + 14 SHAHRIVAR CANONICAL COST"
docker compose exec -T web python manage.py shell -c '
from core.darma_cost_v55 import darma_cost_for
from core.dateutils import parse_jalali_date
from core.models import DiaGallerySale,SaleLine,SaleSnapshot

dates=[parse_jalali_date("1405/06/12"),parse_jalali_date("1405/06/14")]
for line in SaleLine.objects.filter(day__date__in=dates,quantity__gt=0,product_size__product__brand__name__in=["دارما","انبارش"]).select_related("day"):
    snap=SaleSnapshot.objects.filter(sale_line=line).first(); expected=int(darma_cost_for(line.day.date))
    assert snap is not None and int(snap.unit_cost or 0)==expected, (line.id,getattr(snap,"unit_cost",None),expected)
for line in DiaGallerySale.objects.filter(day__date__in=dates,quantity__gt=0).select_related("day"):
    expected=int(darma_cost_for(line.day.date)); assert int(line.unit_cost or 0)==expected, (line.id,line.unit_cost,expected)
print("TARGET_DAYS_COST_VERIFIED=YES")
' || fail "target-day canonical cost verification failed"

step "11) VERIFY EXPECTED REVALUATION + INVARIANTS"
FINAL=$(snapshot_business) || fail "could not capture final business snapshot"
echo "$FINAL"
FINAL_FINISHED=$(getv "$FINAL" FINISHED); FINAL_CAPITAL=$(getv "$FINAL" CAPITAL); FINAL_SNAPSHOTS=$(getv "$FINAL" SALE_SNAPSHOTS)
[ "$FINAL_FINISHED" = "$EXPECTED_FINISHED" ] || fail "FINISHED revaluation mismatch: expected=$EXPECTED_FINISHED actual=$FINAL_FINISHED"
[ "$FINAL_CAPITAL" = "$EXPECTED_CAPITAL" ] || fail "CAPITAL revaluation mismatch: expected=$EXPECTED_CAPITAL actual=$FINAL_CAPITAL"
[ "$FINAL_SNAPSHOTS" = "$EXPECTED_SNAPSHOTS" ] || fail "SaleSnapshot count mismatch: expected=$EXPECTED_SNAPSHOTS actual=$FINAL_SNAPSHOTS"
for field in RAW DIGI DIA DARMA TAKVIN NOVANI SALE_DAYS SALES DIA_SALES ACCOUNT_ENTRIES ADJUSTMENTS TRANSFERS MOVEMENTS OLD_DARMA_MODEL_VALUE BASELINE_DARMA_VALUE; do assert_same_field "$field" "$LIVE" "$FINAL"; done

step "12) SUCCESS"
echo "SUCCESS: DARMA COST RULE V55 DEPLOYED"
echo "SUCCESS: DARMA COST SHAHRIVAR V55 REPAIR APPLIED"
echo "Backup: $BACKUP"
echo "Darma baseline: 61,000 toman per short from 1400/01/01"
echo "12 + 14 Shahrivar: Darma/Anbaresh/s3 snapshots and Dia costs repaired only"
echo "Current Darma inventory revaluation delta: $EXPECTED_DELTA toman"
echo "New cost source: Settings -> Rules and base prices -> Darma cost"
