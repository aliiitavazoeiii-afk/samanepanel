#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

BASE=663ad61339a97dfcd0cc910a82f855dd63dcb7c5

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
BACKUP="backups/before-dia-gallery-v45-${STAMP}.sql"
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
' 2>/dev/null
}

step "3) LIVE BUSINESS SNAPSHOT"
LIVE=$(snapshot_live) || fail "could not capture live business values"
echo "$LIVE"

step "4) SOURCE SCOPE GUARD"
git cat-file -e "$BASE^{commit}" || fail "pre-Dia base missing"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    UI_SAFETY_V45.md|core/daily_report_v8.py|core/daily_views.py|core/dia_gallery_v45.py|core/excel_dashboard.py|core/management/commands/check_dia_gallery_v45.py|core/migrations/0015_dia_gallery_sale.py|core/models.py|core/report_v9.py|core/sale_brand_v19.py|core/urls.py|templates/core/daily_report_v45.html|templates/core/dia_gallery_sale_v45.html|templates/core/report_excel_v45.html|templates/core/sale_brand_v45.html|docs/00_NEW_CHAT_READ_FIRST.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/23_DIA_GALLERY_V45.md|server_dia_gallery_v45.sh) ;;
    *) fail "unexpected V45 file changed: $f" ;;
  esac
done

git diff --quiet "$BASE"..HEAD -- core/finance.py core/inventory_valuation_v17.py core/business_tools_v22.py core/material_report_v22.py core/final_services.py core/cost_accounting_v14.py core/finance_excel_v9.py core/daily_order_import_v23.py core/returns_v37.py core/calculator_v37.py || fail "unrequested protected business source changed"

step "5) BUILD + SOURCE PREFLIGHT"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_returns_calculator_v37 || fail "V37 regression failed"
docker compose run --rm --entrypoint python web manage.py check_digikala_center_v44 || fail "V44 source check failed"
docker compose run --rm --entrypoint python web manage.py check_dia_gallery_v45 --source-only || fail "V45 source check failed"

step "6) VERIFY PREFLIGHT DID NOT CHANGE LIVE BUSINESS VALUES"
PREFLIGHT=$(snapshot_live) || fail "could not capture post-preflight live values"
echo "$PREFLIGHT"
[ "$LIVE" = "$PREFLIGHT" ] || fail "business values changed during V45 preflight"

step "7) RECREATE WEB + APPLY MIGRATION"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 5
docker compose exec -T web python manage.py migrate --check || fail "migration not applied"
docker compose exec -T web python manage.py check || fail "live Django check failed"

step "8) LIVE DIA GALLERY ACCOUNTING ROUNDTRIP"
docker compose exec -T web python manage.py check_dia_gallery_v45 || fail "V45 accounting regression failed"

step "9) FINAL BUSINESS INVARIANTS"
FINAL=$(snapshot_live) || fail "could not capture final business values"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || fail "V45 deployment itself altered business values"

echo ""
echo "======================================"
echo "SUCCESS: DIA GALLERY V45 DEPLOYED"
echo "Backup: $BACKUP"
echo "Dia Gallery: fixed sale price 71000 toman per Darma short"
echo "Dia Gallery: Darma stock decreases on sale"
echo "Dia Gallery: dedicated receivable increases by gross sale"
echo "Dia Gallery: receivable included in accounts and capital"
echo "Dia Gallery: no Digikala fee"
echo "Existing Digikala/XLSX/payment/material/return rules: unchanged"
echo "======================================"
