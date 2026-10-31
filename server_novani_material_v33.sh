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
BACKUP="backups/before-novani-material-v33-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

snapshot_live() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand, ExcelManualRow, ExcelManualSetting, StockBalance
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
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"RAW={raw}")
' 2>/dev/null
}

snapshot_new() {
  docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.models import Brand, ExcelManualRow, ExcelManualSetting, StockBalance
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
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"TAKVIN={bqty(chr(1578)+chr(1705)+chr(1608)+chr(1740)+chr(1606))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"RAW={raw}")
' 2>/dev/null
}

step "3) CAPTURE CURRENT LIVE INVARIANTS"
LIVE=$(snapshot_live) || fail "could not read live invariants"
echo "$LIVE"
CAP_BEFORE=$(printf '%s\n' "$LIVE" | awk -F= '/^CAPITAL=/{print $2}')
DARMA_BEFORE=$(printf '%s\n' "$LIVE" | awk -F= '/^DARMA=/{print $2}')
TAKVIN_BEFORE=$(printf '%s\n' "$LIVE" | awk -F= '/^TAKVIN=/{print $2}')
NOVANI_BEFORE=$(printf '%s\n' "$LIVE" | awk -F= '/^NOVANI=/{print $2}')
RAW_BEFORE=$(printf '%s\n' "$LIVE" | awk -F= '/^RAW=/{print $2}')
[ -n "$CAP_BEFORE" ] || fail "capital before missing"

step "4) BUILD LATEST IMAGE"
docker compose build web || fail "web build failed"

step "5) PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"

step "6) APPLY NOVANI S-SEED MIGRATION (IDEMPOTENT)"
docker compose run --rm --entrypoint python web manage.py migrate || fail "migration failed"

step "7) VERIFY NOVANI SIZE + WRITE ISOLATION"
docker compose run --rm --entrypoint python web manage.py check_novani_material_v33 || fail "Novani v33 isolation check failed"

step "8) VERIFY DEPLOY DID NOT CHANGE BUSINESS VALUES"
NEW=$(snapshot_new) || fail "could not read new-image invariants"
echo "$NEW"
CAP_AFTER=$(printf '%s\n' "$NEW" | awk -F= '/^CAPITAL=/{print $2}')
DARMA_AFTER=$(printf '%s\n' "$NEW" | awk -F= '/^DARMA=/{print $2}')
TAKVIN_AFTER=$(printf '%s\n' "$NEW" | awk -F= '/^TAKVIN=/{print $2}')
NOVANI_AFTER=$(printf '%s\n' "$NEW" | awk -F= '/^NOVANI=/{print $2}')
RAW_AFTER=$(printf '%s\n' "$NEW" | awk -F= '/^RAW=/{print $2}')
[ -n "$CAP_AFTER" ] || fail "capital after missing"
[ -n "$DARMA_AFTER" ] || fail "Darma after missing"
[ -n "$TAKVIN_AFTER" ] || fail "Takvin after missing"
[ -n "$NOVANI_AFTER" ] || fail "Novani after missing"
[ -n "$RAW_AFTER" ] || fail "raw after missing"
[ "$CAP_AFTER" = "$CAP_BEFORE" ] || fail "capital changed during deploy: $CAP_BEFORE -> $CAP_AFTER"
[ "$DARMA_AFTER" = "$DARMA_BEFORE" ] || fail "Darma qty changed during deploy: $DARMA_BEFORE -> $DARMA_AFTER"
[ "$TAKVIN_AFTER" = "$TAKVIN_BEFORE" ] || fail "Takvin qty changed during deploy: $TAKVIN_BEFORE -> $TAKVIN_AFTER"
[ "$NOVANI_AFTER" = "$NOVANI_BEFORE" ] || fail "Novani qty changed during deploy: $NOVANI_BEFORE -> $NOVANI_AFTER"
[ "$RAW_AFTER" = "$RAW_BEFORE" ] || fail "raw materials changed during deploy: $RAW_BEFORE -> $RAW_AFTER"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_novani_material_v33 || fail "live Novani v33 check failed"

step "10) FINAL LIVE INVARIANTS"
FINAL=$(snapshot_live) || fail "could not read final live invariants"
echo "$FINAL"
CAP_FINAL=$(printf '%s\n' "$FINAL" | awk -F= '/^CAPITAL=/{print $2}')
DARMA_FINAL=$(printf '%s\n' "$FINAL" | awk -F= '/^DARMA=/{print $2}')
TAKVIN_FINAL=$(printf '%s\n' "$FINAL" | awk -F= '/^TAKVIN=/{print $2}')
NOVANI_FINAL=$(printf '%s\n' "$FINAL" | awk -F= '/^NOVANI=/{print $2}')
RAW_FINAL=$(printf '%s\n' "$FINAL" | awk -F= '/^RAW=/{print $2}')
[ "$CAP_FINAL" = "$CAP_BEFORE" ] || fail "final capital changed: $CAP_BEFORE -> $CAP_FINAL"
[ "$DARMA_FINAL" = "$DARMA_BEFORE" ] || fail "final Darma qty changed: $DARMA_BEFORE -> $DARMA_FINAL"
[ "$TAKVIN_FINAL" = "$TAKVIN_BEFORE" ] || fail "final Takvin qty changed: $TAKVIN_BEFORE -> $TAKVIN_FINAL"
[ "$NOVANI_FINAL" = "$NOVANI_BEFORE" ] || fail "final Novani qty changed: $NOVANI_BEFORE -> $NOVANI_FINAL"
[ "$RAW_FINAL" = "$RAW_BEFORE" ] || fail "final raw materials changed: $RAW_BEFORE -> $RAW_FINAL"

echo ""
echo "======================================"
echo "SUCCESS: NOVANI MATERIAL SIZES + ISOLATION V33 DEPLOYED"
echo "Backup: $BACKUP"
echo "Novani material sizes: S / M / L / XL / XXL / 3XL"
echo "Darma material sizes: M / L / XL / XXL / 3XL / 4XL (unchanged)"
echo "Novani Apply Output: Novani inventory only"
echo "Darma/Takvin/raw materials/capital during deploy: unchanged"
echo "======================================"
