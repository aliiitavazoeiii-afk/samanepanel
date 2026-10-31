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
BACKUP="backups/before-ui-simplify-returns-v36-${STAMP}.sql"
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

step "4) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "5) PREFLIGHT — NO MIGRATIONS / FORMULAS / ENDPOINT DRIFT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_ui_returns_v36 || fail "v36 UI/return rollback regression check failed"
docker compose run --rm --entrypoint python web manage.py check_operational_roundtrip_v36 || fail "v36 endpoint/accounting roundtrip check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
r=Path("/app/core/report_v9.py").read_text(encoding="utf-8")
d=Path("/app/core/excel_dashboard.py").read_text(encoding="utf-8")
t=Path("/app/templates/core/report_excel_v36.html").read_text(encoding="utf-8")
x=Path("/app/templates/core/_daily_returns_v36.html").read_text(encoding="utf-8")
assert "capital_total = accounts_total + inventory_total + digikala_receivable - takvin_debt + assets_total" in r
assert "sale_line_metrics(line)" in r
assert "qty__lt=10" in d and "قرمز" in d and "زرد" in d
for token in ["گزارش","حساب‌ها","مواد اولیه و موجودی","کالای سرمایه‌ای"]: assert token in t, token
for token in ["مرجوعی","شورت تکی / رنگ","پک کامل / کد","daily_return_add"]: assert token in x, token
print("V36 SOURCE/TEMPLATE SAFETY CHECK OK")
' || fail "source/template safety check failed"

step "6) VERIFY PREFLIGHT CHANGED NOTHING"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during build/preflight"

step "7) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_ui_returns_v36 || fail "live v36 UI/return regression check failed"
docker compose exec -T web python manage.py check_operational_roundtrip_v36 || fail "live v36 endpoint/accounting roundtrip check failed"

step "8) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "deploy changed business values"

echo ""
echo "======================================"
echo "SUCCESS: UI SIMPLIFY + DAILY RETURNS V36 DEPLOYED"
echo "Backup: $BACKUP"
echo "Existing accounting/sale/material formulas: unchanged"
echo "Operational endpoints: route-locked and transactional roundtrip checked"
echo "Payments: Mellat/tailor and material-prepayment apply+reverse checked"
echo "Digikala receipt: Digi/Mellat apply+reverse checked when receivable > 0"
echo "Dashboard alerts: Darma HOME < 10 only; red/yellow product colors excluded"
echo "Daily returns: loose colors first, full-pack codes second; HOME stock only"
echo "Daily returns: no SaleLine, no Digikala fee, no Digikala receivable movement"
echo "Comprehensive report: same data/forms, visually grouped into compact sections"
echo "======================================"
