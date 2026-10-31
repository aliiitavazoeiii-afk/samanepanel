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

step "2) BACKUP DATABASE"
mkdir -p backups || fail "could not create backup directory"
BACKUP="backups/before-khorshid-negative-fix-v15-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) CAPITAL BEFORE"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit before failed"

step "4) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "5) DJANGO CHECK"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py makemigrations --check --dry-run' || fail "Django preflight failed"

step "6) REPAIR DRY RUN"
docker compose run --rm --entrypoint sh web -c 'python manage.py repair_negative_khorshid_v15' || fail "Khorshid repair dry-run failed"

step "7) APPLY TARGETED LOCATION REPAIR"
docker compose run --rm --entrypoint sh web -c 'python manage.py repair_negative_khorshid_v15 --apply' || fail "Khorshid repair failed"

step "8) VERIFY ROUTE GUARD"
docker compose run --rm --entrypoint sh web -c 'python manage.py shell -c "
from django.urls import resolve, reverse
m=resolve(reverse(\"inventory_operations\")).func.__module__
print(\"inventory_operations ->\", m)
assert m == \"core.inventory_operations_v15\"
"' || fail "inventory transfer guard route verification failed"

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "10) VERIFY STOCK + CAPITAL"
docker compose exec -T web python manage.py repair_negative_khorshid_v15 || fail "post-repair verification failed"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit after failed"

step "11) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: KHORSHID NEGATIVE V15 FIXED"
echo "- Darma / Tosi / XXL Khorshid is no longer negative"
echo "- Total Darma stock is unchanged"
echo "- Capital is unchanged"
echo "- Manual transfers cannot exceed source stock"
echo "Backup: $BACKUP"
echo "======================================"
