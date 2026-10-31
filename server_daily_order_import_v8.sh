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
BACKUP="backups/before-daily-order-import-v8-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD FRESH WEB IMAGE"
docker compose build web || fail "Docker build failed"
echo "BUILD OK"

step "4) CHECK MODEL / MIGRATION DRIFT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "5) APPLY MIGRATIONS"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"
echo "MIGRATE OK"

step "6) SYNC PRODUCT CATALOG + GROUP PRICES"
docker compose run --rm --entrypoint sh web -c 'python manage.py sync_excel_product_catalog' || fail "product catalog sync failed"

step "7) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web && python manage.py check_daily_order_import_v8' || fail "preflight failed"
echo "PREFLIGHT OK"

step "8) VERIFY IMPORT ROUTE + FILES"
docker compose run --rm --no-deps --entrypoint sh web -c '
python manage.py shell -c "from django.urls import reverse, resolve; u=reverse(\"daily_order_import\", args=[1]); assert resolve(u).func.__module__ == \"core.daily_order_views_v8\"; print(\"DAILY ORDER IMPORT ROUTE OK\")" &&
grep -Fq "تعداد ارسالی" /app/core/daily_order_import_v8.py &&
grep -Fq "آپلود فایل اکسل دیجی‌کالا" /app/templates/core/_daily_order_upload.html &&
echo "DAILY ORDER IMPORT FILES OK"
' || fail "daily order import route/files verification failed"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "10) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: DAILY ORDER EXCEL IMPORT V8 DEPLOYED"
echo "Backup: $BACKUP"
echo "======================================"
