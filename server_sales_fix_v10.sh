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
BACKUP="backups/before-sales-fix-v10-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD WEB"
docker compose build web || fail "Docker build failed"
echo "BUILD OK"

step "4) CHECK + PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run && python manage.py check && python manage.py check_excel_web && python manage.py check_finance_flow_v9 && python manage.py check_sales_fix_v10' || fail "preflight failed"
echo "PREFLIGHT OK"

step "5) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "6) CURRENT CAPITAL AUDIT"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit failed"

step "7) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: SALES FIX V10 DEPLOYED"
echo "Backup: $BACKUP"
echo "The sale day was NOT deleted automatically."
echo "Run separately when ready:"
echo "docker compose exec -T web python manage.py delete_sale_day_safe 1405/06/01"
echo "======================================"
