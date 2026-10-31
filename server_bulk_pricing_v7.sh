#!/bin/sh

cd /opt/darma-general || exit 1

fail() {
    echo ""
    echo "======================================"
    echo "FAILED: $1"
    echo "======================================"
    exit 1
}

step() {
    echo ""
    echo "======================================"
    echo "$1"
    echo "======================================"
}

step "1) LOAD ENV + START DATABASE"
set -a
. ./.env || fail "could not load .env"
set +a

docker compose up -d db || fail "could not start database"

i=1
while [ "$i" -le 30 ]; do
    if docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        break
    fi
    [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
    sleep 1
    i=$((i + 1))
done
echo "DATABASE OK"

step "2) BACKUP DATABASE"
mkdir -p backups || fail "could not create backup directory"
BACKUP="backups/before-bulk-pricing-v7-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD FRESH WEB IMAGE"
docker compose build --no-cache web || fail "Docker build failed"
echo "BUILD OK"

step "4) CHECK MODEL / MIGRATION DRIFT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "5) APPLY MIGRATIONS"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"
echo "MIGRATE OK"

step "6) SYNC CATALOG + APPLY GROUP PRICES"
docker compose run --rm --entrypoint sh web -c 'python manage.py sync_excel_product_catalog' || fail "catalog/group price sync failed"
echo "GROUP PRICES APPLIED"

step "7) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web' || fail "Django/preflight check failed"
echo "PREFLIGHT OK"

step "8) VERIFY BULK PRICING"
docker compose run --rm --entrypoint sh web -c "python manage.py shell -c \"
from django.urls import resolve
from core.darma_pricing import DEFAULT_GROUP_PRICES, SIZE_NAMES
from core.models import ProductCode

assert resolve('/settings/products/').func.__module__ == 'core.pricing_v7'
assert DEFAULT_GROUP_PRICES[3]['M'] == 385000
assert DEFAULT_GROUP_PRICES[3]['4XL'] == 495000
assert DEFAULT_GROUP_PRICES[4]['M'] == 485000
assert DEFAULT_GROUP_PRICES[4]['4XL'] == 630000
assert DEFAULT_GROUP_PRICES[5]['L'] == 618000
assert DEFAULT_GROUP_PRICES[5]['XXL'] == 701000
assert DEFAULT_GROUP_PRICES[6]['M'] == 699000
assert DEFAULT_GROUP_PRICES[6]['4XL'] == 980000

for pack_qty, price_map in DEFAULT_GROUP_PRICES.items():
    products = ProductCode.objects.filter(brand__name='دارما', pack_qty=pack_qty, active=True).prefetch_related('sizes__size')
    for product in products:
        actual = {ps.size.name: ps.default_sale_price for ps in product.sizes.all() if ps.active}
        for size_name in SIZE_NAMES:
            assert actual.get(size_name) == price_map[size_name], (pack_qty, product.code, size_name, actual.get(size_name), price_map[size_name])

print('BULK PRICING ROUTE OK')
print('DARMA GROUP PRICE VALUES OK')
print('ALL DARMA 3/4/5/6 PACK PRICES OK')
\"" || fail "bulk pricing verification failed"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "10) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: DARMA BULK PRICING V7 DEPLOYED"
echo "Backup: $BACKUP"
echo "======================================"
