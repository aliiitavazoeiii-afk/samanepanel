#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=66d6500b529aed20a42aea4cd9885e8f9e383012

snapshot_economic() {
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
BACKUP="backups/before-daily-report-stability-v48-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP=$BACKUP"

step "2) CAPTURE LIVE BUSINESS INVARIANTS"
docker compose up -d web || fail "web start failed"
sleep 3
LIVE=$(snapshot_economic) || fail "could not capture live economic snapshot"
echo "$LIVE"

step "3) VERIFY V48 CHANGE SCOPE"
git cat-file -e "$BASE^{commit}" || fail "V48 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    templates/core/daily_report_v45.html|core/management/commands/check_daily_report_runtime_v48.py|server_daily_report_stability_v48.sh|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/03_ACTIVE_CODE_MAP.md|docs/PROJECT_CONTEXT/07_BUG_HISTORY_AND_DO_NOT_REPEAT.md|docs/PROJECT_CONTEXT/26_DAILY_REPORT_STABILITY_V48.md|README.md) ;;
    *) fail "unexpected V48 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/models.py core/migrations core/finance.py core/final_services.py core/variant_sale_v12.py core/daily_order_import_v23.py core/finance_excel_v9.py core/inventory_valuation_v17.py core/report_v9.py core/business_tools_v22.py core/material_report_v22.py core/returns_v37.py core/calculator_v37.py || fail "protected business source changed in V48"

step "4) BUILD + PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py shell -c 'from django.template.loader import get_template; get_template("core/daily_report_v45.html"); print("DAILY REPORT TEMPLATE COMPILE OK")' || fail "daily report template compile failed"

step "5) VERIFY PREFLIGHT DID NOT CHANGE BUSINESS VALUES"
PREFLIGHT=$(snapshot_economic) || fail "could not capture post-preflight snapshot"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || {
  echo "--- LIVE ---"; echo "$LIVE"
  echo "--- PREFLIGHT ---"; echo "$PREFLIGHT"
  fail "preflight changed business values"
}

step "6) RECREATE WEB FROM CLEAN V48 IMAGE"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6
docker compose exec -T web python manage.py migrate --check || fail "migration check failed"
docker compose exec -T web python manage.py check || fail "live Django check failed"

step "7) RENDER EVERY EXISTING SALE-DAY REPORT"
docker compose exec -T web python manage.py check_daily_report_runtime_v48 || fail "daily report runtime regression failed"

step "8) VERIFY ZERO BUSINESS CHANGE"
FINAL=$(snapshot_economic) || fail "could not capture final economic snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE V48 ---"; echo "$LIVE"
  echo "--- AFTER V48 ---"; echo "$FINAL"
  fail "V48 changed business/accounting/inventory values"
}

step "9) SUCCESS"
echo "SUCCESS: DAILY REPORT STABILITY V48 DEPLOYED"
echo "Backup: $BACKUP"
echo "Daily report: all existing sale days rendered HTTP 200"
echo "Business/accounting/inventory formulas: unchanged"
echo "UI theme: no intentional redesign in V48"
