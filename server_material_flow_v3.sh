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

step "1) LOAD ENVIRONMENT + START DATABASE"
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

step "2) BACKUP CURRENT DATABASE"
mkdir -p backups || fail "could not create backup directory"
BACKUP="backups/before-material-flow-v3-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD WEB IMAGE"
docker compose build web || fail "Docker build failed"
echo "BUILD OK"

step "4) VERIFY MIGRATION STATE"
docker compose run --rm --entrypoint sh web -c '
    python manage.py makemigrations --check --dry-run
' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "5) APPLY MIGRATIONS"
docker compose run --rm --entrypoint sh web -c '
    python manage.py migrate --noinput
' || fail "migration failed"
echo "MIGRATE OK"

step "6) RUN CHECKS"
docker compose run --rm --entrypoint sh web -c '
    python manage.py check && python manage.py check_excel_web
' || fail "Django/preflight check failed"
echo "PREFLIGHT OK"

step "7) VERIFY MATERIAL FLOW MODELS"
docker compose run --rm --entrypoint sh web -c "python manage.py shell -c \"
from core.models import RawMaterialStock, MaterialReportConsumption
print('RawMaterialStock rows:', RawMaterialStock.objects.count())
print('MaterialReportConsumption rows:', MaterialReportConsumption.objects.count())
print('MATERIAL FLOW MODELS OK')
\"" || fail "material flow model verification failed"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web container"
docker compose restart caddy || fail "could not restart caddy"

step "9) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: MATERIAL FLOW V3 DEPLOYED"
echo "Backup: $BACKUP"
echo "======================================"
