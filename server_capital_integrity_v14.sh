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
BACKUP="backups/before-capital-integrity-v14-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) CAPITAL BEFORE FIX"
docker compose exec -T web python manage.py capital_audit_v9 || fail "could not read current capital"

step "4) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "5) CHECK MODEL / MIGRATION DRIFT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "6) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "7) PREFLIGHT V14"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web && python manage.py check_finance_flow_v9 && python manage.py check_capital_integrity_v14' || fail "v14 preflight failed"
echo "PREFLIGHT V14 OK"

step "8) LEGACY REPAIR DRY RUN"
docker compose run --rm --entrypoint sh web -c 'python manage.py repair_capital_state_v14' || fail "legacy repair dry-run found a conflict"

step "9) RECREATE LIVE WEB ON V14"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "10) APPLY ONE-TIME LEGACY REPAIR"
docker compose exec -T web python manage.py repair_capital_state_v14 --apply || fail "legacy repair failed; database transaction rolled back"

step "11) CAPITAL AFTER FIX"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit failed"
docker compose exec -T web python manage.py check_capital_integrity_v14 || fail "capital integrity check failed"

step "12) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: CAPITAL INTEGRITY V14 DEPLOYED"
echo "Backup: $BACKUP"
echo "Rules now enforced:"
echo "- Save material report = data only, zero stock/capital effect"
echo "- Apply production = raw materials out + finished goods in + tailor wage, atomically"
echo "- Unapply production = exact opposite, atomically"
echo "- Digikala receipt/delete = receivable and Mellat move together"
echo "- Material purchase/delete = stock and Mellat move together through durable ledger"
echo "======================================"
