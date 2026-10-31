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
BACKUP="backups/before-material-split-v16-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) CAPITAL BEFORE DEPLOY"
CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | tee /tmp/capital-before-v16.txt | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2); print $2}' | tail -1)
[ -n "$CAP_BEFORE" ] || fail "could not read capital before deploy"
echo "CAPITAL BEFORE = $CAP_BEFORE"

step "4) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "5) MODEL / MIGRATION CHECK"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "6) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "7) PREFLIGHT V16"
docker compose run --rm --entrypoint sh web -c '
python manage.py check &&
python manage.py check_excel_web &&
python manage.py check_finance_flow_v9 &&
python manage.py check_capital_integrity_v14 &&
python manage.py check_material_split_v16 &&
python manage.py shell -c "from django.template.loader import get_template; get_template(\"core/material_report_v16.html\"); print(\"MATERIAL V16 TEMPLATE OK\")"
' || fail "v16 preflight failed"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "9) CAPITAL AFTER DEPLOY"
CAP_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9 | tee /tmp/capital-after-v16.txt | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2); print $2}' | tail -1)
[ -n "$CAP_AFTER" ] || fail "could not read capital after deploy"
echo "CAPITAL AFTER  = $CAP_AFTER"
if [ "$CAP_BEFORE" != "$CAP_AFTER" ]; then
    echo "CAPITAL BEFORE = $CAP_BEFORE"
    echo "CAPITAL AFTER  = $CAP_AFTER"
    fail "capital changed during a code-only v16 deploy"
fi

echo "CAPITAL UNCHANGED: $CAP_AFTER"

step "10) RUNTIME CHECK"
docker compose exec -T web python manage.py check_material_split_v16 || fail "live v16 runtime check failed"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: MATERIAL SPLIT V16 DEPLOYED"
echo "Backup: $BACKUP"
echo "Capital stayed unchanged: $CAP_AFTER"
echo "No inventory repair/reset was performed."
echo "- Save = data only"
echo "- Apply materials = raw materials only, delta-based"
echo "- Apply output = only newly delivered shorts, cumulative/delta-based"
echo "======================================"
