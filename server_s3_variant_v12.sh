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

step "2) BACKUP CURRENT DATABASE"
mkdir -p backups || fail "could not create backup directory"
BACKUP="backups/before-s3-variant-v12-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "4) CHECK MODEL / MIGRATION DRIFT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "5) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "6) SYNC CURRENT CATALOG + S3"
docker compose run --rm --entrypoint sh web -c 'python manage.py sync_excel_product_catalog && python manage.py sync_s3_variant_v12' || fail "catalog/s3 sync failed"

step "7) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web && python manage.py check_finance_flow_v9 && python manage.py check_s3_variant_v12' || fail "preflight failed"
echo "PREFLIGHT OK"

step "8) VERIFY V12 RUNTIME"
docker compose run --rm --no-deps --entrypoint sh web -c 'python manage.py shell -c "
from django.template.loader import get_template
from core.daily_order_import_v12 import apply_delivery_report
from core.variant_sale_v12 import resolve_variant_color, SELLER_COLOR_CODES
assert callable(apply_delivery_report)
assert SELLER_COLOR_CODES.get(\"s2\") == \"کرم\"
assert SELLER_COLOR_CODES.get(\"s3\") == \"مشکی\"
assert SELLER_COLOR_CODES.get(\"S3\") == \"صورتی\"
assert SELLER_COLOR_CODES.get(\"s5\") == \"سرمه ای\"
assert resolve_variant_color(\"شورت زنانه دارما مدل s3 | XXL | سفید | گارانتی\", \"\") == \"سفید\"
assert resolve_variant_color(\"شورت زنانه دارما مدل s3 | 3XL | کرم | گارانتی\", \"s2\") == \"کرم\"
get_template(\"core/settings_products.html\")
print(\"S3 V12 RUNTIME CHECK OK\")
"' || fail "v12 runtime verification failed"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "10) CAPITAL + DARMA INVENTORY CHECK"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit failed"
docker compose exec -T web python manage.py reconcile_darma_excel_v11 || fail "Darma inventory dry-run failed"

step "11) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: S3 VARIABLE-COLOR V12 DEPLOYED"
echo "Backup: $BACKUP"
echo "IMPORTANT: Before uploading a file containing s3, set Darma pack-1 prices in Settings > Products and codes."
echo "======================================"
