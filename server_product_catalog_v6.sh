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
BACKUP="backups/before-product-catalog-v6-$(date +%Y%m%d-%H%M%S).sql"
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

step "6) SYNC EXCEL PRODUCT CATALOG"
docker compose run --rm --entrypoint sh web -c 'python manage.py sync_excel_product_catalog' || fail "product catalog sync failed"

step "7) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web' || fail "Django/preflight check failed"
echo "PREFLIGHT OK"

step "8) VERIFY PRODUCT CATALOG + FINAL DARMA PRICES"
docker compose run --rm --entrypoint sh web -c "python manage.py shell -c \"
from core.brand_colors import norm
from core.models import ProductCode
from core.product_catalog import CATALOG, DARMA_PRICE_BY_PACK


def comp(brand, code):
    p = ProductCode.objects.prefetch_related('composition__color').get(brand__name=brand, code=code)
    return {norm(x.color.name): x.qty for x in p.composition.all()}

assert len(CATALOG['تکوین']) == 15
assert len(CATALOG['دارما']) == 17
assert not ProductCode.objects.filter(brand__name='دارما', code__in=['rah','blk']).exists()
assert comp('تکوین','4444') == {norm('بنفش'):1, norm('سرمه ای'):1, norm('چرک روشن'):1}
assert comp('تکوین','555-1') == {norm('طوسی'):1, norm('سرمه ای'):1, norm('سفید'):1, norm('چرک روشن'):1, norm('مشکی'):1}
assert comp('دارما','rah-110') == {norm('راه راه'):1, norm('سفید'):1, norm('سرمه ای'):1}
assert comp('دارما','rah-220') == {norm('راه راه طوسی'):1, norm('سفید'):1, norm('طوسی'):1}
assert ProductCode.objects.get(brand__name='دارما', code='p12').pack_qty == 12
assert ProductCode.objects.get(brand__name='دارما', code='06').pack_qty == 6

for code, spec in CATALOG['دارما'].items():
    pack_qty = sum(int(v) for v in spec['composition'].values())
    if pack_qty not in DARMA_PRICE_BY_PACK:
        continue
    product = ProductCode.objects.get(brand__name='دارما', code=code)
    actual = {
        row.size.name: int(row.default_sale_price)
        for row in product.sizes.select_related('size').filter(active=True)
    }
    expected = DARMA_PRICE_BY_PACK[pack_qty]
    assert actual == expected, (code, pack_qty, actual, expected)

print('TAKVIN CATALOG:', len(CATALOG['تکوین']))
print('DARMA CATALOG:', len(CATALOG['دارما']))
print('REMOVED CODES ABSENT: rah, blk')
for pack_qty in [3,4,5,6]:
    print('DARMA PACK', pack_qty, 'PRICES OK:', DARMA_PRICE_BY_PACK[pack_qty])
print('FINAL DARMA PRICE SCHEDULE OK')
print('PRODUCT CATALOG CHECK OK')
\"" || fail "product catalog / Darma price verification failed"

step "9) VERIFY PRODUCTION DESTINATION"
docker compose run --rm --no-deps --entrypoint sh web -c '
grep -Fq "warehouse = StockLocation.objects.get(key=StockLocation.KHORSHID)" /app/core/material_report_v5.py &&
grep -Fq "موجودی انبار دارما" /app/templates/core/material_report.html &&
echo "PRODUCTION DESTINATION CHECK OK"
' || fail "production destination is not warehouse"

step "10) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "11) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: PRODUCT CATALOG V6 DEPLOYED"
echo "Backup: $BACKUP"
echo "======================================"
