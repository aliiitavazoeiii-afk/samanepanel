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
BACKUP="backups/before-brand-colors-production-v5-$(date +%Y%m%d-%H%M%S).sql"
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

step "6) DJANGO + EXCEL-WEB PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web' || fail "Django/preflight check failed"
echo "PREFLIGHT OK"

step "7) VERIFY BRAND COLOR SEPARATION"
docker compose run --rm --entrypoint sh web -c "python manage.py shell -c \"
from core.brand_colors import colors_for_brand, norm, TAKVIN_COLORS
from core.models import Brand

darma = Brand.objects.get(name='دارما')
takvin = Brand.objects.get(name='تکوین')
d = list(colors_for_brand(darma).values_list('name', flat=True))
t = list(colors_for_brand(takvin).values_list('name', flat=True))

expected_t = {norm(x) for x in TAKVIN_COLORS}
actual_t = {norm(x) for x in t}
assert actual_t == expected_t, (sorted(t), sorted(TAKVIN_COLORS))

exclusive_t = {norm(x) for x in ['طوسی راه راه','بنفش','چرک روشن','راه راه بنفش','راه راه سفید مشکی','راه راه زرد','متفرقه','راه راه سفید','راه راه مشکی']}
assert not ({norm(x) for x in d} & exclusive_t), d

print('DARMA COLORS:', len(d))
print('TAKVIN COLORS:', len(t))
print('BRAND COLOR SEPARATION OK')
\"" || fail "brand color separation verification failed"

step "8) VERIFY V5 ROUTES + WAGE RULE"
docker compose run --rm --entrypoint sh web -c "python manage.py shell -c \"
from django.urls import resolve
from core.material_report_v5 import _wage_for_pieces

assert resolve('/report/').func.__module__ == 'core.report_v5'
assert resolve('/inventory/').func.__module__ == 'core.inventory_v5'
assert resolve('/settings/catalog/').func.__module__ == 'core.catalog_v5'
assert resolve('/settings/stock/').func.__module__ == 'core.settings_stock_v5'
assert resolve('/payments/').func.__module__ == 'core.business_tools_v5'
assert resolve('/takvin/').func.__module__ == 'core.takvin_v5'
assert resolve('/material-report/').func.__module__ == 'core.material_report_v5'
assert _wage_for_pieces(12, 110000) == 110000
assert _wage_for_pieces(24, 110000) == 220000
print('V5 ROUTES OK')
print('SEWING WAGE RULE OK: 110000 PER DOZEN')
\"" || fail "v5 route/wage verification failed"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "10) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: BRAND COLORS + TAKVIN + PRODUCTION V5 DEPLOYED"
echo "Backup: $BACKUP"
echo "======================================"
