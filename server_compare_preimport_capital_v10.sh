#!/bin/sh

cd /opt/darma-general || exit 1

fail() {
  echo ""
  echo "======================================"
  echo "FAILED: $1"
  echo "======================================"
  exit 1
}

set -a
. ./.env || fail "could not load .env"
set +a

BACKUP=$(ls -1t backups/before-daily-order-import-v8-*.sql 2>/dev/null | head -n 1)
[ -n "$BACKUP" ] || fail "no before-daily-order-import-v8 backup found"
[ -s "$BACKUP" ] || fail "selected backup is empty"

TMPDB="darma_preimport_compare_v10"

echo "======================================"
echo "CURRENT DATABASE"
echo "======================================"
docker compose exec -T web python manage.py capital_audit_v9 || fail "current capital audit failed"

echo ""
echo "Using backup: $BACKUP"
echo ""

echo "======================================"
echo "RESTORE BACKUP TO TEMP DATABASE"
echo "======================================"
docker compose exec -T db dropdb -U "$DB_USER" --if-exists "$TMPDB" >/dev/null 2>&1 || true
docker compose exec -T db createdb -U "$DB_USER" "$TMPDB" || fail "could not create temporary database"
docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$DB_USER" -d "$TMPDB" < "$BACKUP" >/tmp/darma-preimport-restore.log 2>&1 || {
  docker compose exec -T db dropdb -U "$DB_USER" --if-exists "$TMPDB" >/dev/null 2>&1 || true
  cat /tmp/darma-preimport-restore.log
  fail "temporary backup restore failed"
}

echo "RESTORE OK"

echo ""
echo "======================================"
echo "PRE-IMPORT BACKUP DATABASE"
echo "======================================"
docker compose run --rm -e DB_NAME="$TMPDB" --entrypoint sh web -c 'python manage.py capital_audit_v9' || {
  docker compose exec -T db dropdb -U "$DB_USER" --if-exists "$TMPDB" >/dev/null 2>&1 || true
  fail "backup capital audit failed"
}

echo ""
echo "======================================"
echo "CLEANUP TEMP DATABASE"
echo "======================================"
docker compose exec -T db dropdb -U "$DB_USER" --if-exists "$TMPDB" || fail "could not remove temporary database"
echo "TEMP DATABASE REMOVED"
echo ""
echo "This script never changed the live database."
