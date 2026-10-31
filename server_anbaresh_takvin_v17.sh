#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1; i=$((i+1))
done

step "2) BACKUP"
mkdir -p backups
BACKUP="backups/before-anbaresh-takvin-v17-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP: $BACKUP"

step "3) CAPITAL BEFORE"
BEFORE_CAPITAL=""
if docker compose ps --status running web 2>/dev/null | grep -q web; then
  BEFORE_CAPITAL=$(docker compose exec -T web python manage.py capital_audit_v9 2>/dev/null | awk -F= '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1 || true)
fi
echo "CAPITAL BEFORE = ${BEFORE_CAPITAL:-unknown}"

step "4) BUILD"
docker compose build web || fail "web build failed"

step "5) MIGRATION DRIFT CHECK"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"

step "6) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "7) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web && python manage.py check_v17_features' || fail "v17 preflight failed"

step "8) CAPITAL AFTER MIGRATION"
AFTER_CAPITAL=$(docker compose run --rm --entrypoint sh web -c 'python manage.py capital_audit_v9' | awk -F= '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
echo "CAPITAL AFTER = $AFTER_CAPITAL"
if [ -n "$BEFORE_CAPITAL" ] && [ "$BEFORE_CAPITAL" != "$AFTER_CAPITAL" ]; then
  fail "capital changed during deployment: before=$BEFORE_CAPITAL after=$AFTER_CAPITAL. Live web was NOT replaced."
fi

step "9) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"

step "10) FINAL CHECK"
docker compose exec -T web python manage.py check_v17_features || fail "live v17 check failed"
docker compose exec -T web python manage.py capital_audit_v9 || fail "live capital audit failed"

echo ""
echo "======================================"
echo "SUCCESS: ANBARESH + TAKVIN PRICING V17 DEPLOYED"
echo "Backup: $BACKUP"
echo "No Darma stock repair was performed. The old -50 gray/XXL Khorshid row was intentionally left untouched."
echo "======================================"
