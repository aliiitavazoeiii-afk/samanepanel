#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

MARKER='V47 BLACK RED UI RUNTIME OVERLAY'

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

step "1) BACKUP DATABASE BEFORE ROLLBACK"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL not ready"
  sleep 1; i=$((i+1))
done
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-v47-ui-rollback-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup empty"
echo "BACKUP=$BACKUP"

step "2) CAPTURE BUSINESS INVARIANTS"
docker compose up -d web || fail "web start failed"
sleep 3
LIVE=$(snapshot_economic) || fail "could not capture business snapshot"
echo "$LIVE"

step "3) REBUILD CLEAN IMAGE FROM CURRENT GIT SOURCE"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy >/dev/null || fail "caddy restart failed"
sleep 6

step "4) VERIFY OLD UI IS RESTORED"
docker compose exec -T web sh -c "! grep -q '$MARKER' /app/static/core/ui-polish.css" || fail "V47 overlay still present after clean recreate"
docker compose exec -T web python - <<'PY' || fail "template verification failed"
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE","config.settings")
import django; django.setup()
from django.template.loader import get_template
for name in ("base.html","core/report_excel_v45.html"):
    get_template(name)
    print("TEMPLATE OK", name)
PY

step "5) VERIFY ZERO BUSINESS CHANGE"
FINAL=$(snapshot_economic) || fail "could not capture final business snapshot"
echo "$FINAL"
[ "$LIVE" = "$FINAL" ] || {
  echo "--- BEFORE ROLLBACK ---"; echo "$LIVE"
  echo "--- AFTER ROLLBACK ---"; echo "$FINAL"
  fail "UI rollback changed business values"
}

echo ""
echo "======================================"
echo "SUCCESS: BLACK RED UI V47 ROLLED BACK"
echo "Database backup: $BACKUP"
echo "Original pre-V47 visual source restored from clean image"
echo "Business/accounting/inventory values unchanged"
echo "======================================"
