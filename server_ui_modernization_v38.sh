#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=b488fee9701e1a4b4c266dd92aa371db5d159e99

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
BACKUP="backups/before-ui-modernization-v38-${STAMP}.sql"
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

step "4) V38 SOURCE-SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-v38 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    static/core/ui-polish.css|UI_SAFETY_V38.md|server_ui_modernization_v38.sh|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/03_ACTIVE_CODE_MAP.md|docs/PROJECT_CONTEXT/09_UI_AND_USER_WORKFLOW_CONTRACT.md|docs/PROJECT_CONTEXT/12_VERSION_TIMELINE_V18_TO_V37.md|docs/PROJECT_CONTEXT/15_CODE_FINGERPRINT_AT_HANDOFF.md|docs/PROJECT_CONTEXT/16_UI_MODERNIZATION_V38.md) ;;
    *) fail "unexpected V38 file changed: $f" ;;
  esac
done

# UI-only V38 must not alter any Python, route, template, migration or workflow JS.
git diff --quiet "$BASE"..HEAD -- core templates static/core/number_format.js static/core/jalali_picker.js static/core/material_report_v5.js static/core/raw_materials.js static/core/raw_materials_v3.js || fail "protected application/template/workflow source changed in V38"

step "5) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "6) PREFLIGHT — NO MIGRATIONS / BUSINESS DRIFT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 operational regression check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
css=Path("/app/static/core/ui-polish.css").read_text(encoding="utf-8")
base=Path("/app/templates/base.html").read_text(encoding="utf-8")
urls=Path("/app/core/urls.py").read_text(encoding="utf-8")
finance=Path("/app/core/finance.py").read_text(encoding="utf-8")
report=Path("/app/core/report_v9.py").read_text(encoding="utf-8")
assert "V38 UI modernization layer" in css
assert css.count("{") == css.count("}"), "unbalanced CSS braces"
assert "core/ui-polish.css" in base
assert "returns_v37.returns_home" in urls and "calculator_v37.calculator" in urls
assert "def digikala_fee_for_unit" in finance
assert "capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total" in report
print("V38 UI SOURCE SAFETY CHECK OK")
' || fail "V38 UI source safety check failed"

step "7) VERIFY PREFLIGHT CHANGED NOTHING"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during V38 build/preflight"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 operational regression check failed"

step "9) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V38 cosmetic deploy changed business values"

echo ""
echo "======================================"
echo "SUCCESS: UI MODERNIZATION V38 DEPLOYED"
echo "Backup: $BACKUP"
echo "V38 application change: static/core/ui-polish.css only"
echo "Routes/Python/templates/models/migrations/workflow JS: unchanged"
echo "Accounting/inventory/sales/material/payment/return/calculator semantics: unchanged"
echo "All protected economic invariants: unchanged"
echo "======================================"
