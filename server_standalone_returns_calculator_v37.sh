#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "2) FULL DATABASE BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-standalone-returns-calculator-v37-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

snapshot_live() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
print(f"CAPITAL={capital}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null
}

snapshot_new() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import AccountEntry, Brand, ExcelManualRow, ExcelManualSetting, SaleLine, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
print(f"CAPITAL={capital}")
print(f"FINISHED={finished}")
print(f"RAW={raw}")
print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}")
print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null
}

step "3) CAPTURE LIVE BUSINESS VALUES"
LIVE=$(snapshot_live) || fail "could not read live business values"
echo "$LIVE"

step "4) SOURCE-SCOPE GUARD"
BASE=669801bf7ea261a5e41b5ef30f37799a4e185bae
git cat-file -e "$BASE^{commit}" || fail "v37 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    UI_SAFETY_V37.md|core/returns_v37.py|core/calculator_v37.py|core/urls.py|core/daily_report_v8.py|core/management/commands/check_returns_calculator_v37.py|templates/core/returns_v37.html|templates/core/calculator_v37.html|templates/core/_calculator_target_result_v37.html|static/core/number_format.js|server_standalone_returns_calculator_v37.sh) ;;
    *) fail "unexpected v37 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/finance.py core/report_v9.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/final_services.py || fail "protected formula/finance/material file changed in v37"

step "5) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "6) PREFLIGHT — NO MIGRATIONS + V37 REGRESSION"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "v37 regression check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
u=Path("/app/core/urls.py").read_text(encoding="utf-8")
d=Path("/app/core/daily_report_v8.py").read_text(encoding="utf-8")
f=Path("/app/core/finance.py").read_text(encoding="utf-8")
r=Path("/app/core/report_v9.py").read_text(encoding="utf-8")
n=Path("/app/static/core/number_format.js").read_text(encoding="utf-8")
assert "daily_return_add" not in u
assert "returns_v37.returns_home" in u and "returns_v37.return_apply" in u
assert "calculator_v37.calculator" in u and "calculator_target_quote" in u
assert "daily_report_v36" not in d and "daily_return" not in d
assert "core/daily_report_v21.html" in d
assert "def digikala_fee_for_unit" in f and "digikala_processing_floor" in f and "digikala_vat_percent" in f
assert "capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total" in r
assert "dataset.returnsNav" in n and "/returns/" in n
print("V37 SOURCE SAFETY CHECK OK")
' || fail "v37 source safety check failed"

step "7) VERIFY PREFLIGHT CHANGED NOTHING"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during v37 preflight"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live v37 regression check failed"

step "9) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "deploy changed business values"

echo ""
echo "======================================"
echo "SUCCESS: STANDALONE RETURNS + CALCULATOR V37 DEPLOYED"
echo "Backup: $BACKUP"
echo "Old daily-report return box/route: removed"
echo "Sidebar: standalone Returns added under daily work"
echo "Returns: color/code -> brand -> size -> HOME only"
echo "Returns: no sale/profit/Digikala/account movement"
echo "Calculator: current-month Darma/Takvin profit-on-cost preserved with exact existing Digikala fee engine"
echo "Protected accounting/finance/material formulas: unchanged"
echo "======================================"
