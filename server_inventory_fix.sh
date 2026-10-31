#!/bin/sh

# Reliable one-command production update for the Excel-Web inventory reset.
# Intentionally does NOT use `set -e`; every destructive step is guarded and
# reports exactly where it failed. Run with: bash server_inventory_fix.sh

cd /opt/darma-general || exit 1

fail() {
    echo ""
    echo "======================================"
    echo "FAILED: $1"
    echo "======================================"
    echo "Nothing after this step was executed."
    exit 1
}

step() {
    echo ""
    echo "======================================"
    echo "$1"
    echo "======================================"
}

step "1) VERIFY SOURCE CODE"
echo "Commit: $(git rev-parse HEAD 2>/dev/null || echo unknown)"
grep -Fq "قیمت تمام‌شده هر عدد" templates/core/inventory_final.html || fail "new inventory template is not present"
grep -Fq "InventoryModelCost" core/models_final.py || fail "InventoryModelCost model is not present"
test -f core/migrations/0005_inventory_model_cost.py || fail "migration 0005 is missing"
grep -Fq 'TAKVIN_TOTAL = 1310' core/management/commands/reset_and_load_darma_inventory.py || fail "Takvin reset data is missing"
echo "SOURCE CODE OK"

step "2) LOAD ENVIRONMENT + START DATABASE"
set -a
. ./.env || fail "could not load .env"
set +a

docker compose up -d db || fail "could not start database"

DB_READY=0
i=1
while [ "$i" -le 30 ]; do
    if docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        DB_READY=1
        break
    fi
    echo "Waiting for PostgreSQL... ($i/30)"
    sleep 1
    i=$((i + 1))
done

[ "$DB_READY" -eq 1 ] || fail "PostgreSQL did not become ready"
echo "DATABASE OK"

step "3) BACKUP CURRENT DATABASE"
mkdir -p backups || fail "could not create backups directory"
BACKUP="backups/before-inventory-reset-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "4) REBUILD WEB IMAGE WITHOUT CACHE"
docker compose build --no-cache web || fail "Docker build failed"
echo "BUILD OK"

step "5) VERIFY NEW IMAGE CONTENT"
docker compose run --rm --no-deps --entrypoint sh web -c '
    grep -Fq "قیمت تمام‌شده هر عدد" /app/templates/core/inventory_final.html &&
    grep -Fq "InventoryModelCost" /app/core/models_final.py &&
    test -f /app/core/migrations/0005_inventory_model_cost.py &&
    grep -Fq "TAKVIN_TOTAL = 1310" /app/core/management/commands/reset_and_load_darma_inventory.py
' || fail "new Docker image still contains old code"
echo "IMAGE CODE OK"

step "6) MIGRATE + PREFLIGHT"
docker compose run --rm --entrypoint sh web -c '
    python manage.py migrate --noinput &&
    python manage.py check &&
    python manage.py check_excel_web
' || fail "migration or preflight failed"
echo "MIGRATION + PREFLIGHT OK"

step "7) RESET BUSINESS DATA + LOAD DARMA AND TAKVIN"
docker compose stop web >/dev/null 2>&1 || true

docker compose run --rm --entrypoint sh web -c '
    python manage.py reset_and_load_darma_inventory --yes
' || {
    docker compose up -d web >/dev/null 2>&1 || true
    fail "inventory reset/import failed"
}
echo "RESET + IMPORT OK"

step "8) START FRESH LIVE CONTAINER"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy >/dev/null 2>&1 || true
sleep 3

step "9) VERIFY LIVE CODE"
docker compose exec -T web sh -c '
    grep -Fq "قیمت تمام‌شده هر عدد" /app/templates/core/inventory_final.html &&
    grep -Fq "inventory-capital-row" /app/templates/core/inventory_final.html &&
    grep -Fq "InventoryModelCost" /app/core/models_final.py
' || fail "live web container is still running old code"
echo "LIVE UI CODE OK"

step "10) VERIFY DATABASE INVENTORY + COSTS"
docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance, InventoryModelCost


def inspect(name):
    brand = Brand.objects.get(name=name)
    rows = StockBalance.objects.filter(brand=brand).select_related("color", "size", "location")
    home = 0
    value = 0
    for row in rows:
        cost = (InventoryModelCost.objects
                .filter(brand=brand, color=row.color, size=row.size)
                .values_list("unit_cost", flat=True)
                .first() or 0)
        if row.location.key == "home":
            home += row.qty
        value += row.qty * cost
    models = StockBalance.objects.filter(brand=brand).values("color_id").distinct().count()
    costs = InventoryModelCost.objects.filter(brand=brand).count()
    return home, value, models, costs


dh, dv, dm, dc = inspect("دارما")
th, tv, tm, tc = inspect("تکوین")
kh = StockBalance.objects.filter(brand__name="دارما", location__key="khorshid").aggregate(v=Sum("qty"))["v"] or 0

print("========== FINAL CHECK ==========")
print("DARMA HOME       :", dh)
print("DARMA KHORSHID   :", kh)
print("DARMA MODELS     :", dm)
print("DARMA COST ROWS  :", dc)
print("DARMA CAPITAL    :", dv)
print("TAKVIN HOME      :", th)
print("TAKVIN MODELS    :", tm)
print("TAKVIN COST ROWS :", tc)
print("TAKVIN CAPITAL   :", tv)
print("=================================")

assert dh == 14873, dh
assert kh == 0, kh
assert dm == 13, dm
assert dc == 78, dc
assert dv == 907253000, dv
assert th == 1310, th
assert tm == 15, tm
assert tc == 60, tc
assert tv == 173416500, tv
print("ALL INVENTORY CHECKS PASSED")
' || fail "final database verification failed"

step "11) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS"
echo "======================================"
echo "Backup: $BACKUP"
echo "Now refresh the website with Ctrl+F5."
