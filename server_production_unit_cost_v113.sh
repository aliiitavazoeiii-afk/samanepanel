#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=d6f0fe2bede06a5d72bb39d9e71ce920d533654f

echo "=== CHECK BRANCH AND DIFF ==="
git cat-file -e "$BASE^{commit}" || fail "V112 base missing"
test "$(git branch --show-current)" = "v113-unit-production-cost-calculator" || fail "wrong branch"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    PROJECT_HANDOFF_CURRENT.md|docs/PROJECT_CONTEXT/README.md|docs/PROJECT_CONTEXT/62_PRODUCTION_COST_V113.md|templates/core/calculator_v37.html|core/management/commands/check_production_unit_cost_v113.py|server_production_unit_cost_v113.sh) ;;
    *) fail "unexpected changed file: $f" ;;
  esac
done

echo "=== BACKUP + LIVE PRE-SNAPSHOT ==="
docker compose config -q || fail "invalid compose"
docker compose ps --status running web | grep -q web || fail "live web not running"
docker compose exec -T web python manage.py showmigrations core | grep -Fq "[X] 0019_material_output_location" || fail "V112 migration 0019 not applied; deploy V112 first"
mkdir -p backups
BACKUP="backups/before-production-cost-v113-$(date +%Y%m%d-%H%M%S).sql"
set -a
. ./.env
set +a
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "DB backup failed"
test -s "$BACKUP" || fail "backup empty"
HASH_CODE='from hashlib import sha256
from django.apps import apps
names=["StockBalance","InventoryMovement","RawMaterialStock","MaterialReportBlock","MaterialReportOutputApplied","MaterialReportOutputLocation","BusinessPayment","AccountEntry","SaleLine","ProductCode","ProductSize"]
for name in names:
 m=apps.get_model("core",name)
 cols=[f.attname for f in m._meta.concrete_fields]
 h=sha256()
 for row in m.objects.order_by("pk").values_list(*cols):
  h.update(repr(row).encode());h.update(b"\\n")
 print(name+"="+h.hexdigest())'
PRE=$(docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)=' ) || fail "PRE snapshot failed"
echo "$PRE"

echo "=== BUILD AND REGRESSIONS (BEFORE RECREATE) ==="
docker compose build web || fail "build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check"
docker compose run --rm --entrypoint python web manage.py check_final_baseline_v108 || fail "V108 regression"
docker compose run --rm --entrypoint python web manage.py check_finance_calculator_v104 || fail "legacy calculator regression"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110 regression"
docker compose run --rm --entrypoint python web manage.py check_material_output_destination_v112 || fail "V112 regression"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "V113 regression"

PROJECTED=$(docker compose run --rm --entrypoint python web manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)=' ) || fail "PROJECTED snapshot failed"
test "$PRE" = "$PROJECTED" || { echo "$PRE"; echo "$PROJECTED"; fail "business state mismatch before cutover"; }

echo "=== LIVE CUTOVER ==="
docker compose up -d --no-deps --force-recreate web || fail "recreate failed"
sleep 6
docker compose exec -T web python manage.py check || fail "live Django check"
docker compose exec -T web python manage.py check_finance_calculator_v104 || fail "live original calculator regression"
docker compose exec -T web python manage.py check_production_unit_cost_v113 || fail "live V113 regression"
FINAL=$(docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)=' ) || fail "FINAL snapshot failed"
test "$PRE" = "$FINAL" || { echo "$PRE"; echo "$FINAL"; fail "business state mismatch after cutover"; }
echo "SUCCESS: PRODUCTION UNIT COST CALCULATOR V113 DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP: $BACKUP"
