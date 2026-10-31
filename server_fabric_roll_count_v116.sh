#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=f6424fe0be725833e8f54247c5cc45c0d40b3634

echo "=== V116 FABRIC ROLL CORRECTION ==="
test "$(git branch --show-current)" = "v116-fabric-roll-count-audit" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V115 parent commit missing"
git diff --quiet || fail "local tracked changes exist; safeguard other UI work"
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
 case "$f" in
   core/material_report_v92.py|templates/core/material_report_v92.html|core/management/commands/check_material_summary_box_grid_v110.py|core/management/commands/check_fabric_roll_count_v116.py|docs/PROJECT_CONTEXT/65_FABRIC_ROLL_COUNT_V116.md|docs/PROJECT_CONTEXT/README.md|PROJECT_HANDOFF_CURRENT.md|server_fabric_roll_count_v116.sh) ;;
   *) fail "unexpected changed file: $f" ;;
 esac
done
git diff --quiet "$BASE"..HEAD -- core/models.py core/migrations core/material_report_v23.py core/finance_overview_v104.py core/calculator_v37.py core/inventory_v20.py core/sale_entry_v60.py || fail "protected logic changed"

echo "=== BACKUP / BUSINESS HASH ==="
docker compose config -q || fail "compose invalid"
docker compose ps --status running web | grep -q web || fail "live web not running"
test -f .env || fail ".env not found"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v116-fabric-roll-correction-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
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
snapshot_live(){ docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)='; }
snapshot_image(){ docker compose run --rm --entrypoint python web manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E '^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize)='; }
PRE=$(snapshot_live) || fail "PRE hash error"
echo "$PRE"

echo "=== BUILD / READ ONLY REGRESSION ==="
docker compose build web || fail "build failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check"
docker compose run --rm --entrypoint python web manage.py check_stable_sidebar_report_v115 || fail "V115 regression failed"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110+V116 material summary regression failed"
docker compose run --rm --entrypoint python web manage.py check_fabric_roll_count_v116 || fail "V116 roll count audit failed"
docker compose run --rm --entrypoint python web manage.py check_final_baseline_v108 || fail "V108 regression failed"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "V113 calculator regression failed"
PROJECTED=$(snapshot_image) || fail "PROJECTED hash error"
test "$PRE" = "$PROJECTED" || { echo "$PROJECTED"; fail "business hash changed before deploy"; }

echo "=== LIVE RECREATE ==="
docker compose up -d --no-deps --force-recreate web || fail "web recreate failed"
sleep 6
docker compose exec -T web python manage.py check_stable_sidebar_report_v115 || fail "live V115 check failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110+V116 regression failed"
docker compose exec -T web python manage.py check_fabric_roll_count_v116 || fail "live V116 audit failed"
docker compose exec -T web python manage.py check_production_unit_cost_v113 || fail "live V113 check failed"
FINAL=$(snapshot_live) || fail "FINAL hash error"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business hash changed after deploy"; }
echo "SUCCESS: FABRIC ROLL COUNT V116 DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
