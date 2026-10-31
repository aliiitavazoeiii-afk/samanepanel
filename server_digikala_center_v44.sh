#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=9bedc210706ab022307961ae1ba97d5a5807fb84
RUNTIME_SECRET=/opt/darma-secrets/digikala/runtime

step "1) VERIFY DIGIKALA SECRETS"
[ -s "$RUNTIME_SECRET/access_token.txt" ] || fail "runtime access token missing"
[ -s "$RUNTIME_SECRET/refresh_token.txt" ] || fail "runtime refresh token missing"
[ ! -e "$RUNTIME_SECRET/private_key.pem" ] || fail "private key must not be mounted into web runtime"

step "2) START DATABASE"
docker compose config -q || fail "compose invalid"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done

step "3) BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-digikala-center-v44-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup empty"
echo "BACKUP=$BACKUP"

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
finished=int(finished_inventory_value_v17()); raw=int(_raw_material_context()["materials_total"]); digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}"); print(f"RAW={raw}"); print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}"); print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
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
finished=int(finished_inventory_value_v17()); raw=int(_raw_material_context()["materials_total"]); digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
print(f"CAPITAL={accounts+assets+finished+raw+digi-debt}")
print(f"FINISHED={finished}"); print(f"RAW={raw}"); print(f"DIGI={digi}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"SALES={SaleLine.objects.count()}"); print(f"ACCOUNT_ENTRIES={AccountEntry.objects.count()}")
' 2>/dev/null
}

step "4) LIVE BUSINESS SNAPSHOT"
LIVE=$(snapshot_live) || fail "could not capture live business values"
echo "$LIVE"

step "5) SOURCE SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-V44 base missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    UI_SAFETY_V44.md|config/settings.py|core/digikala_center_v44.py|core/digikala_shared_v44.py|core/digikala_views_v40.py|core/digikala_warehouse_v42.py|core/management/commands/check_digikala_center_v44.py|core/urls.py|templates/core/_digikala_nav_v43.html|templates/core/digikala_center_v43.html|templates/core/digikala_packages_v43.html|templates/core/digikala_products_v44.html|templates/core/digikala_returns_v43.html|templates/core/digikala_sales_v43.html|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/22_DIGIKALA_CENTER_V44.md|server_digikala_center_v44.sh) ;;
    *) fail "unexpected V44 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/finance.py core/report_v9.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/final_services.py core/cost_accounting_v14.py core/finance_excel_v9.py core/daily_order_import_v23.py core/returns_v37.py core/calculator_v37.py core/models.py core/migrations compose.yml || fail "protected business source changed"

step "6) BUILD + PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 regression failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_v40 || fail "V40 source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_delivery_v41 || fail "V41 source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_warehouse_v42 || fail "V42 source check failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_center_v44 || fail "V44 source check failed"

step "7) VERIFY PREFLIGHT DID NOT CHANGE BUSINESS VALUES"
NEW=$(snapshot_new) || fail "could not read new-image business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during V44 preflight"

step "8) RECREATE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_returns_calculator_v37 || fail "live V37 regression failed"

step "9) LIVE V44 API CHECK + CACHE WARMUP"
docker compose exec -T web python manage.py check_digikala_center_v44 --live || fail "V44 live API check failed"

step "10) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V44 read-only changes altered business values"

echo ""
echo "======================================"
echo "SUCCESS: DIGIKALA CENTER V44 DEPLOYED"
echo "Backup: $BACKUP"
echo "Fixed: tomorrow/day-after split + product lists"
echo "Added: /digikala/products/ from Inventory API"
echo "Fixed: sales endpoint fallback"
echo "Fixed: physical return warehouse detection"
echo "Performance: shared multi-worker cache + bounded concurrent pagination"
echo "Internal accounting/inventory/sales/XLSX semantics: unchanged"
echo "======================================"
