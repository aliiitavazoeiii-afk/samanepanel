#!/bin/sh
set -eu
cd /opt/darma-general

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

EXPECTED_BEFORE_FINISHED=989089500
EXPECTED_BEFORE_INVENTORY=3129036600
EXPECTED_BEFORE_CAPITAL=5485315435

set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DB + REQUIRE V17 LIVE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
    if docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        break
    fi
    [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
    sleep 1
    i=$((i + 1))
done

docker compose exec -T web python manage.py check_v17_features \
    || fail "V17 is not confirmed live. Deploy server_anbaresh_takvin_v17.sh first; no Darma stock was changed."

step "2) FULL PRE-CHANGE CAPITAL AUDIT"
AUDIT_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9) \
    || fail "could not read live capital audit"
printf '%s\n' "$AUDIT_BEFORE"

FINISHED_BEFORE=$(printf '%s\n' "$AUDIT_BEFORE" | awk -F'= ' '/FINISHED INVENTORY/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
RAW_BEFORE=$(printf '%s\n' "$AUDIT_BEFORE" | awk -F'= ' '/RAW MATERIALS/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
CAPITAL_BEFORE=$(printf '%s\n' "$AUDIT_BEFORE" | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)

[ -n "$FINISHED_BEFORE" ] || fail "could not parse FINISHED INVENTORY"
[ -n "$RAW_BEFORE" ] || fail "could not parse RAW MATERIALS"
[ -n "$CAPITAL_BEFORE" ] || fail "could not parse CAPITAL TOTAL"

INVENTORY_BEFORE=$((FINISHED_BEFORE + RAW_BEFORE))

echo "CHECKED FINISHED BEFORE  = $FINISHED_BEFORE"
echo "CHECKED INVENTORY BEFORE = $INVENTORY_BEFORE"
echo "CHECKED CAPITAL BEFORE   = $CAPITAL_BEFORE"

[ "$FINISHED_BEFORE" -eq "$EXPECTED_BEFORE_FINISHED" ] \
    || fail "finished inventory differs from user baseline: live=$FINISHED_BEFORE expected=$EXPECTED_BEFORE_FINISHED"
[ "$INVENTORY_BEFORE" -eq "$EXPECTED_BEFORE_INVENTORY" ] \
    || fail "inventory total differs from user baseline: live=$INVENTORY_BEFORE expected=$EXPECTED_BEFORE_INVENTORY"
[ "$CAPITAL_BEFORE" -eq "$EXPECTED_BEFORE_CAPITAL" ] \
    || fail "capital differs from user baseline: live=$CAPITAL_BEFORE expected=$EXPECTED_BEFORE_CAPITAL"

step "3) BACKUP DATABASE"
mkdir -p backups
BACKUP="backups/before-darma-physical-v18-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" \
    || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP: $BACKUP"

step "4) UPDATE/BUILD + SAFE CHECKS"
git pull --ff-only || fail "git pull failed"
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' \
    || fail "model/migration drift detected"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' \
    || fail "migration failed"
docker compose run --rm --entrypoint sh web -c \
    'python manage.py check && python manage.py check_excel_web && python manage.py check_v17_features' \
    || fail "preflight failed"

step "5) DARMA PHYSICAL V18 DRY RUN"
DRY_RUN=$(docker compose run --rm --entrypoint sh web -c 'python manage.py reconcile_darma_physical_v18') \
    || fail "physical baseline dry-run failed"
printf '%s\n' "$DRY_RUN"

EXPECTED_FINISHED_AFTER=$(printf '%s\n' "$DRY_RUN" | awk -F'= ' '/EXPECTED FINISHED AFTER/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
EXPECTED_INVENTORY_AFTER=$(printf '%s\n' "$DRY_RUN" | awk -F'= ' '/EXPECTED INVENTORY AFTER/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
EXPECTED_CAPITAL_AFTER=$(printf '%s\n' "$DRY_RUN" | awk -F'= ' '/EXPECTED CAPITAL AFTER/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_TARGET_VALUE=$(printf '%s\n' "$DRY_RUN" | awk -F'= ' '/DARMA TARGET VALUE/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_VALUE_DELTA=$(printf '%s\n' "$DRY_RUN" | awk -F'= ' '/DARMA VALUE DELTA/{gsub(/[[:space:]+]/,"",$2);print $2}' | tail -1)

[ -n "$EXPECTED_FINISHED_AFTER" ] || fail "could not parse expected finished inventory"
[ -n "$EXPECTED_INVENTORY_AFTER" ] || fail "could not parse expected inventory total"
[ -n "$EXPECTED_CAPITAL_AFTER" ] || fail "could not parse expected capital"
[ -n "$DARMA_TARGET_VALUE" ] || fail "could not parse Darma target value"

echo "EXPECTED FINISHED AFTER  = $EXPECTED_FINISHED_AFTER"
echo "EXPECTED INVENTORY AFTER = $EXPECTED_INVENTORY_AFTER"
echo "EXPECTED CAPITAL AFTER   = $EXPECTED_CAPITAL_AFTER"
echo "DARMA TARGET VALUE       = $DARMA_TARGET_VALUE"
echo "DARMA VALUE DELTA        = ${DARMA_VALUE_DELTA:-unknown}"

step "6) STOP WEB BRIEFLY + APPLY ATOMIC BASELINE"
WEB_STOPPED=0
restore_web() {
    if [ "$WEB_STOPPED" -eq 1 ]; then
        echo "Restoring previous web container..."
        docker compose start web >/dev/null 2>&1 || true
    fi
}
trap restore_web EXIT INT TERM

docker compose stop web || fail "could not stop web before stock baseline"
WEB_STOPPED=1

APPLY_OUTPUT=$(docker compose run --rm --entrypoint sh web -c 'python manage.py reconcile_darma_physical_v18 --apply') \
    || fail "physical baseline apply failed; database transaction was rolled back"
printf '%s\n' "$APPLY_OUTPUT"
printf '%s\n' "$APPLY_OUTPUT" | grep -q 'DARMA PHYSICAL BASELINE V18 APPLIED' \
    || fail "apply did not report success"

step "7) START NEW LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate live web"
WEB_STOPPED=0
trap - EXIT INT TERM
docker compose restart caddy || fail "caddy restart failed"

step "8) FINAL CAPITAL + INVENTORY VERIFICATION"
AUDIT_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9) \
    || fail "could not read final capital audit"
printf '%s\n' "$AUDIT_AFTER"

FINISHED_AFTER=$(printf '%s\n' "$AUDIT_AFTER" | awk -F'= ' '/FINISHED INVENTORY/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
RAW_AFTER=$(printf '%s\n' "$AUDIT_AFTER" | awk -F'= ' '/RAW MATERIALS/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
CAPITAL_AFTER=$(printf '%s\n' "$AUDIT_AFTER" | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
INVENTORY_AFTER=$((FINISHED_AFTER + RAW_AFTER))

[ "$RAW_AFTER" -eq "$RAW_BEFORE" ] \
    || fail "raw materials changed unexpectedly: before=$RAW_BEFORE after=$RAW_AFTER"
[ "$FINISHED_AFTER" -eq "$EXPECTED_FINISHED_AFTER" ] \
    || fail "finished inventory mismatch: actual=$FINISHED_AFTER expected=$EXPECTED_FINISHED_AFTER"
[ "$INVENTORY_AFTER" -eq "$EXPECTED_INVENTORY_AFTER" ] \
    || fail "inventory total mismatch: actual=$INVENTORY_AFTER expected=$EXPECTED_INVENTORY_AFTER"
[ "$CAPITAL_AFTER" -eq "$EXPECTED_CAPITAL_AFTER" ] \
    || fail "capital mismatch: actual=$CAPITAL_AFTER expected=$EXPECTED_CAPITAL_AFTER"

VERIFY=$(docker compose exec -T web python manage.py reconcile_darma_physical_v18) \
    || fail "final physical baseline verification failed"
printf '%s\n' "$VERIFY"
printf '%s\n' "$VERIFY" | grep -q 'CHANGED CELLS = 0' \
    || fail "final Darma matrix is not idempotent / still has pending differences"

step "SUCCESS"
echo "DARMA PHYSICAL BASELINE 1405/06/03 APPLIED"
echo "HOME QTY       = 4585"
echo "KHORSHID QTY   = 8890"
echo "TOTAL QTY      = 13475"
echo "FINISHED AFTER = $FINISHED_AFTER"
echo "INVENTORY AFTER= $INVENTORY_AFTER"
echo "CAPITAL AFTER  = $CAPITAL_AFTER"
echo "BACKUP         = $BACKUP"
echo "Sales and SaleSnapshots were not rewritten."
