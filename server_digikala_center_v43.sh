#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=a1af5a867834b24fefdbcac78c9166ab9b28587a
SECRET_ROOT=/opt/darma-secrets/digikala
RUNTIME_SECRET="$SECRET_ROOT/runtime"

step "1) VERIFY DIGIKALA RUNTIME SECRETS"
[ -d "$RUNTIME_SECRET" ] || fail "Digikala runtime secret directory missing: $RUNTIME_SECRET"
[ -s "$RUNTIME_SECRET/access_token.txt" ] || fail "runtime access token missing"
[ -s "$RUNTIME_SECRET/refresh_token.txt" ] || fail "runtime refresh token missing"
[ ! -e "$RUNTIME_SECRET/private_key.pem" ] || fail "RSA private key must not be in web runtime directory"
chmod 700 "$RUNTIME_SECRET"
chmod 600 "$RUNTIME_SECRET/access_token.txt" "$RUNTIME_SECRET/refresh_token.txt"

step "2) START DATABASE"
docker compose config -q || fail "docker compose configuration invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "3) FULL DATABASE BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-digikala-center-v43-${STAMP}.sql"
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

step "4) CAPTURE LIVE BUSINESS VALUES"
LIVE=$(snapshot_live) || fail "could not read live business values"
echo "$LIVE"

step "5) V43 SOURCE-SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-v43 base missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    core/digikala_center_v43.py|core/digikala_views_v40.py|core/urls.py|core/management/commands/check_digikala_center_v43.py|templates/core/_digikala_nav_v43.html|templates/core/digikala_center_v43.html|templates/core/digikala_orders_v43.html|templates/core/digikala_packages_v43.html|templates/core/digikala_package_detail_v43.html|templates/core/digikala_sales_v43.html|templates/core/digikala_returns_v43.html|templates/core/digikala_warehouse_v42.html|server_digikala_center_v43.sh|UI_SAFETY_V43.md|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/03_ACTIVE_CODE_MAP.md|docs/PROJECT_CONTEXT/08_LIVE_STATE_AND_CHECKPOINTS.md|docs/PROJECT_CONTEXT/21_DIGIKALA_CENTER_V43.md) ;;
    *) fail "unexpected V43 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/finance.py core/report_v9.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/final_services.py core/cost_accounting_v14.py core/finance_excel_v9.py core/daily_order_import_v23.py core/returns_v37.py core/calculator_v37.py core/models.py core/migrations compose.yml || fail "protected business/model/secret-mount source changed in V43"

step "6) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "7) PREFLIGHT SOURCE + REGRESSION CHECKS"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 regression failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_v40 || fail "V40 source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_delivery_v41 || fail "V41 source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_warehouse_v42 || fail "V42 warehouse source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_center_v43 || fail "V43 center source check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
center=Path("/app/core/digikala_center_v43.py").read_text(encoding="utf-8")
views=Path("/app/core/digikala_views_v40.py").read_text(encoding="utf-8")
urls=Path("/app/core/urls.py").read_text(encoding="utf-8")
assert "get_json" in center
assert "get_daily_orders_center" in center
assert "get_packages_board" in center
assert "get_sales_board" in center
assert "get_returns_board" in center
assert "search[to_commitment_date]" in center
assert "digikala_center_v43.html" in views
for route in ("digikala/orders/", "digikala/packages/", "digikala/sales/", "digikala/returns/"):
    assert route in urls
assert "SaleLine.objects" not in center
assert "StockBalance.objects" not in center
assert "AccountEntry.objects" not in center
assert Path("/run/secrets/digikala/access_token.txt").is_file()
assert Path("/run/secrets/digikala/refresh_token.txt").is_file()
assert not Path("/run/secrets/digikala/private_key.pem").exists()
print("V43 SOURCE / ISOLATION / SECRET SAFETY CHECK OK")
' || fail "V43 source safety failed"

step "8) VERIFY PREFLIGHT CHANGED NO BUSINESS VALUES"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during V43 preflight"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 regression failed"

step "10) LIVE DIGIKALA CENTER CHECKS"
docker compose exec -T web python manage.py check_digikala_v40 --live || fail "live V40 API check failed"
docker compose exec -T web python manage.py check_digikala_delivery_v41 --live || fail "live V41 delivery check failed"
docker compose exec -T web python manage.py check_digikala_center_v43 --live || fail "live V43 center check failed"

echo "Waiting for Digikala API rate-limit window before full warehouse reconciliation..."
sleep 65
docker compose exec -T web python manage.py check_digikala_warehouse_v42 --live || fail "live V42 warehouse check failed"

step "11) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V43 read-only Digikala Center changed business values"

echo ""
echo "======================================"
echo "SUCCESS: DIGIKALA CENTER V43 DEPLOYED"
echo "Backup: $BACKUP"
echo "Routes: /digikala/ /digikala/orders/ /digikala/packages/ /digikala/sales/ /digikala/warehouse/ /digikala/returns/"
echo "V43 mode: external Digikala read-only center"
echo "Package -> daily report bridge: NOT ENABLED"
echo "Digikala return -> HOME bridge: NOT ENABLED"
echo "Accounting/inventory/sales/XLSX/material/payment/return/calculator semantics: unchanged"
echo "All protected economic invariants: unchanged"
echo "======================================"
