#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE + REQUIRE LIVE WEB"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done
docker compose ps --status running web | grep -q web || fail "live web container is not running"

step "2) VERIFY EXACT KNOWN BAD CELLS"
CELL_BEFORE=$(docker compose exec -T web python manage.py shell -c '
from core.models import Brand,Color,Size,StockBalance,StockLocation
b=Brand.objects.get(name="دارما"); s=Size.objects.get(name="XXL"); l=StockLocation.objects.get(key=StockLocation.KHORSHID)
def q(name):
 c=Color.objects.get(name=name); return int(StockBalance.objects.filter(brand=b,size=s,color=c,location=l).values_list("qty",flat=True).first() or 0)
print(f"{q(chr(1602)+chr(1585)+chr(1605)+chr(1586))}|{q(chr(1705)+chr(1585)+chr(1605))}")
' 2>/dev/null | tail -1)
RED_BEFORE=$(printf '%s' "$CELL_BEFORE" | cut -d'|' -f1)
CREAM_BEFORE=$(printf '%s' "$CELL_BEFORE" | cut -d'|' -f2)
echo "قرمز / XXL / خورشید BEFORE = $RED_BEFORE"
echo "کرم / XXL / خورشید BEFORE = $CREAM_BEFORE"

if [ "$RED_BEFORE" = "0" ] && [ "$CREAM_BEFORE" = "400" ]; then
  echo "ALREADY CORRECT: no database change needed."
  exit 0
fi
[ "$RED_BEFORE" = "140" ] || fail "red XXL Khorshid is no longer 140; refusing to overwrite newer stock"
[ "$CREAM_BEFORE" = "260" ] || fail "cream XXL Khorshid is no longer 260; refusing to overwrite newer stock"

step "3) BACKUP + BEFORE AUDIT"
mkdir -p backups
BACKUP="backups/before-khorshid-red-cream-xxl-v20-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP: $BACKUP"

CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
[ -n "$CAP_BEFORE" ] || fail "could not read capital before"
DARMA_BEFORE=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ -n "$DARMA_BEFORE" ] || fail "could not read Darma total before"
COSTS=$(docker compose exec -T web python manage.py shell -c '
from core.models import Brand,Color,InventoryModelCost,Size
b=Brand.objects.get(name="دارما"); s=Size.objects.get(name="XXL")
def cost(name):
 c=Color.objects.get(name=name); return int(InventoryModelCost.objects.filter(brand=b,size=s,color=c).values_list("unit_cost",flat=True).first() or 0)
print(f"{cost(chr(1602)+chr(1585)+chr(1605)+chr(1586))}|{cost(chr(1705)+chr(1585)+chr(1605))}")
' 2>/dev/null | tail -1)
RED_COST=$(printf '%s' "$COSTS" | cut -d'|' -f1)
CREAM_COST=$(printf '%s' "$COSTS" | cut -d'|' -f2)
EXPECTED_CAP_DELTA=$((140 * (CREAM_COST - RED_COST)))
EXPECTED_CAP_AFTER=$((CAP_BEFORE + EXPECTED_CAP_DELTA))
echo "CAPITAL BEFORE = $CAP_BEFORE"
echo "DARMA QTY BEFORE = $DARMA_BEFORE"
echo "RED XXL COST = $RED_COST"
echo "CREAM XXL COST = $CREAM_COST"
echo "EXPECTED CAPITAL DELTA = $EXPECTED_CAP_DELTA"

step "4) BUILD NEW IMAGE + PREFLIGHT"
docker compose build web || fail "web image build failed"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py correct_khorshid_red_cream_xxl_v20 || fail "correction dry-run failed"

step "5) APPLY ATOMIC TWO-CELL CORRECTION"
docker compose run --rm --entrypoint python web manage.py correct_khorshid_red_cream_xxl_v20 --apply || fail "correction apply failed"

step "6) VERIFY CELLS + TOTAL + CAPITAL"
CELL_AFTER=$(docker compose exec -T web python manage.py shell -c '
from core.models import Brand,Color,Size,StockBalance,StockLocation
b=Brand.objects.get(name="دارما"); s=Size.objects.get(name="XXL"); l=StockLocation.objects.get(key=StockLocation.KHORSHID)
def q(name):
 c=Color.objects.get(name=name); return int(StockBalance.objects.filter(brand=b,size=s,color=c,location=l).values_list("qty",flat=True).first() or 0)
print(f"{q(chr(1602)+chr(1585)+chr(1605)+chr(1586))}|{q(chr(1705)+chr(1585)+chr(1605))}")
' 2>/dev/null | tail -1)
RED_AFTER=$(printf '%s' "$CELL_AFTER" | cut -d'|' -f1)
CREAM_AFTER=$(printf '%s' "$CELL_AFTER" | cut -d'|' -f2)
DARMA_AFTER=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
CAP_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)

[ "$RED_AFTER" = "0" ] || fail "red XXL Khorshid is not 0 after correction"
[ "$CREAM_AFTER" = "400" ] || fail "cream XXL Khorshid is not 400 after correction"
[ "$DARMA_AFTER" = "$DARMA_BEFORE" ] || fail "Darma total quantity changed: before=$DARMA_BEFORE after=$DARMA_AFTER"
[ "$CAP_AFTER" = "$EXPECTED_CAP_AFTER" ] || fail "capital delta mismatch: expected=$EXPECTED_CAP_AFTER actual=$CAP_AFTER"

docker compose run --rm --entrypoint python web manage.py check_capital_integrity_v14 || fail "capital integrity check failed"

echo ""
echo "======================================"
echo "SUCCESS: KHORSHID RED/CREAM XXL CORRECTED"
echo "قرمز / XXL / خورشید: 140 -> 0"
echo "کرم / XXL / خورشید: 260 -> 400"
echo "Darma total unchanged: $DARMA_AFTER"
echo "Capital before: $CAP_BEFORE"
echo "Capital after:  $CAP_AFTER"
echo "Capital delta:  $EXPECTED_CAP_DELTA"
echo "Backup: $BACKUP"
echo "======================================"
