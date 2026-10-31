#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=524b314ed3324aa658983eae5d823cf8ad858be7

step "1) START DATABASE"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done

step "2) BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-no-auto-transfer-v46-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup empty"
echo "BACKUP=$BACKUP"

snapshot_economic() {
  # Keep only invariant key=value lines. Django can print an automatic-import
  # banner whose object count may differ before/after image recreation; that is
  # not business state and must never trip the economic guard.
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
try:
    from core.dia_gallery_v45 import dia_gallery_receivable_total
    dia=int(dia_gallery_receivable_total())
except Exception:
    dia=0
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS])) + dia
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17()); raw=int(_raw_material_context()["materials_total"]); digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}"); print(f"RAW={raw}"); print(f"DIGI={digi}"); print(f"DIA={dia}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}"); print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null | grep -E '^(CAPITAL|FINISHED|RAW|DIGI|DIA|DARMA|TAKVIN|NOVANI|SALES|ACCOUNT_ENTRIES)='
}

snapshot_locations() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance, StockLocation
b=Brand.objects.get(name="دارما")
h=StockLocation.objects.get(key=StockLocation.HOME)
k=StockLocation.objects.get(key=StockLocation.KHORSHID)
def q(loc): return int(StockBalance.objects.filter(brand=b,location=loc).aggregate(v=Sum("qty"))["v"] or 0)
print(f"DARMA_HOME={q(h)}")
print(f"DARMA_KHORSHID={q(k)}")
print(f"DARMA_COMBINED={q(h)+q(k)}")
' 2>/dev/null | grep -E '^DARMA_(HOME|KHORSHID|COMBINED)='
}

step "3) LIVE ECONOMIC SNAPSHOT"
LIVE=$(snapshot_economic) || fail "could not capture live economic values"
LOC_BEFORE=$(snapshot_locations) || fail "could not capture Darma location values"
echo "$LIVE"
echo "$LOC_BEFORE"

step "4) SOURCE SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "V46 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/final_services.py|core/variant_sale_v12.py|core/management/commands/reconcile_no_auto_transfer_v46.py|core/management/commands/check_no_auto_transfer_v46.py|templates/core/report_excel_v45.html|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/24_NO_AUTO_TRANSFER_V46.md|UI_SAFETY_V46.md|server_no_auto_transfer_v46.sh) ;;
    *) fail "unexpected V46 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/finance.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/cost_accounting_v14.py core/finance_excel_v9.py core/daily_order_import_v23.py core/returns_v37.py core/calculator_v37.py core/models.py || fail "protected accounting/import/model source changed"

step "5) BUILD + SOURCE PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py shell -c 'from django.template.loader import get_template; get_template("core/report_excel_v45.html"); print("COMPREHENSIVE REPORT TEMPLATE OK")' || fail "comprehensive report template compile failed"
docker compose run --rm --entrypoint python web manage.py check_no_auto_transfer_v46 --source-only || fail "V46 source check failed"
docker compose run --rm --entrypoint python web manage.py reconcile_no_auto_transfer_v46 || fail "V46 reversal dry-run failed"

step "6) VERIFY PREFLIGHT DID NOT CHANGE LIVE ECONOMICS"
PREFLIGHT=$(snapshot_economic) || fail "could not capture post-preflight values"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- LIVE ---"; echo "$LIVE"
  echo "--- PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "economic values changed during preflight"
}

step "7) RECREATE WEB WITH HOME-ONLY SALE POLICY"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 5
docker compose exec -T web python manage.py migrate --check || fail "migration check failed"
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py shell -c 'from django.template.loader import get_template; get_template("core/report_excel_v45.html"); print("LIVE COMPREHENSIVE REPORT TEMPLATE OK")' || fail "live comprehensive report template compile failed"
docker compose exec -T web python manage.py check_no_auto_transfer_v46 || fail "V46 functional rollback test failed"

step "8) REVERSE HISTORICAL PHANTOM AUTO-TRANSFERS AFTER DAY-3 BASELINE"
docker compose exec -T web python manage.py reconcile_no_auto_transfer_v46 --apply || fail "V46 historical reversal failed"

step "9) VERIFY LOCATION + ECONOMIC INVARIANTS"
FINAL=$(snapshot_economic) || fail "could not capture final economic values"
LOC_AFTER=$(snapshot_locations) || fail "could not capture final Darma locations"
echo "$FINAL"
echo "$LOC_AFTER"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- LIVE ---"; echo "$LIVE"
  echo "--- FINAL ---"; echo "$FINAL"
  fail "V46 changed economic totals/capital"
}
docker compose exec -T web python manage.py reconcile_no_auto_transfer_v46 || fail "V46 post-apply verification failed"

echo ""
echo "======================================"
echo "SUCCESS: NO AUTO-TRANSFER V46 DEPLOYED"
echo "Backup: $BACKUP"
echo "Sales: HOME only; negative HOME is allowed"
echo "KHORSHID: never touched by a sale automatically"
echo "Manual transfer: KHORSHID decreases and HOME increases by entered quantity"
echo "Historical phantom auto-transfers after the 3-Shahrivar physical baseline were reversed"
echo "Comprehensive report template: compiled successfully"
echo "Combined Darma quantity/value and capital were preserved"
echo "======================================"
