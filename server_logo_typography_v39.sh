#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=33e96888fc000a346f1fd0abdcbf8f982d3bdc01

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
BACKUP="backups/before-logo-typography-v39-${STAMP}.sql"
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

step "4) V39 SOURCE-SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-v39 base commit missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    static/core/darma-logo-v39.webp|static/core/ui-v39.css|static/core/number_format.js|UI_SAFETY_V39.md|server_logo_typography_v39.sh|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md|docs/PROJECT_CONTEXT/09_UI_AND_USER_WORKFLOW_CONTRACT.md|docs/PROJECT_CONTEXT/17_LOGO_TYPOGRAPHY_V39.md) ;;
    *) fail "unexpected V39 file changed: $f" ;;
  esac
done

# V39 is presentation-only. Core Python, templates, models and migrations are frozen.
git diff --quiet "$BASE"..HEAD -- core templates static/core/ui-polish.css static/core/jalali_picker.js static/core/material_report_v5.js static/core/raw_materials.js static/core/raw_materials_v3.js || fail "protected application/template source changed in V39"

step "5) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "6) PREFLIGHT — NO MIGRATIONS / BUSINESS DRIFT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 operational regression check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
css=Path("/app/static/core/ui-v39.css").read_text(encoding="utf-8")
js=Path("/app/static/core/number_format.js").read_text(encoding="utf-8")
logo=Path("/app/static/core/darma-logo-v39.webp")
finance=Path("/app/core/finance.py").read_text(encoding="utf-8")
report=Path("/app/core/report_v9.py").read_text(encoding="utf-8")
urls=Path("/app/core/urls.py").read_text(encoding="utf-8")
assert "V39" in css and "darma-logo-v39.webp" in css
assert css.count("{") == css.count("}"), "unbalanced V39 CSS braces"
assert logo.exists() and logo.stat().st_size > 10000, "V39 logo asset missing/too small"
assert "injectV39Styles" in js and "/static/core/ui-v39.css?v=39" in js
for token in ["function raw(value)","function grouped(value)","function bind(root = document)","function injectToolNav()","window.DarmaNumber = { raw, grouped, separator: SEP }"]:
    assert token in js, token
assert "returns_v37.returns_home" in urls and "calculator_v37.calculator" in urls
assert "def digikala_fee_for_unit" in finance
assert "capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total" in report
print("V39 LOGO/TYPOGRAPHY SOURCE SAFETY CHECK OK")
' || fail "V39 source safety check failed"

step "7) VERIFY PREFLIGHT CHANGED NOTHING"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during V39 build/preflight"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 operational regression check failed"

step "9) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V39 presentation deploy changed business values"

echo ""
echo "======================================"
echo "SUCCESS: LOGO + TYPOGRAPHY V39 DEPLOYED"
echo "Backup: $BACKUP"
echo "Darma logo: added as static/core/darma-logo-v39.webp"
echo "Typography: simplified Persian weights/spacing in static/core/ui-v39.css"
echo "V38 stylesheet/core templates/Python/models/migrations: unchanged"
echo "Number formatting/navigation semantics: preserved; only V39 stylesheet loader added"
echo "Accounting/inventory/sales/material/payment/return/calculator semantics: unchanged"
echo "All protected economic invariants: unchanged"
echo "======================================"
