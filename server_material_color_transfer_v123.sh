#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=163ef2c8d4094f4fd162c0a978554bc708361e29

echo "=== V123 COLOR MATERIAL APPLICATION + TWO-WAY STOCK TRANSFER ==="
test "$(git branch --show-current)" = "v123-material-color-apply-inventory-transfer" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V122 parent commit missing"
git diff --quiet -- . ':(exclude)Caddyfile' || fail "other tracked local changes exist"
git diff --cached --quiet -- . ':(exclude)Caddyfile' || fail "other staged local changes exist"
git diff --quiet "$BASE"..HEAD -- Caddyfile || fail "V122 must not change Caddyfile"
test -f Caddyfile || fail "Caddyfile missing"
CADDY_BEFORE=$(sha256sum Caddyfile | awk '{print $1}')
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    .github/workflows/check-material-v123.yml|PROJECT_HANDOFF_CURRENT.md|core/inventory_operations_v16.py|core/inventory_transfer_v123.py|core/inventory_v20.py|core/management/commands/check_inventory_alert_v123.py|core/management/commands/check_material_net_v122.py|core/management/commands/check_material_summary_box_grid_v110.py|core/management/commands/check_material_transfer_v123.py|core/material_color_apply_v123.py|core/material_color_models_v123.py|core/material_report_v20.py|core/material_report_v23.py|core/material_report_v92.py|core/migrations/0021_material_color_use_v123.py|core/models.py|core/test_material_color_v123.py|core/urls.py|docs/PROJECT_CONTEXT/71_MATERIAL_COLOR_APPLY_BIDIRECTIONAL_TRANSFER_V123.md|docs/PROJECT_CONTEXT/README.md|server_material_color_transfer_v123.sh|templates/core/inventory_operations.html|templates/core/inventory_v19.html|templates/core/material_report_v36.html|templates/core/material_report_v92.html) ;;
    *) fail "unexpected V123 file: $f" ;;
  esac
done
# Production ERP data, finance, materials synchronization, stock and all
# existing HTML sidebar/business templates MUST be identical to V121.
git diff --quiet "$BASE"..HEAD -- \
    core/material_receipt_sync.py core/material_flow.py core/wholesale_logic_v119.py \
    core/business_tools_v14.py core/capital_history_v87.py \
    core/finance_overview_v104.py core/sale_entry_v60.py templates/base.html \
    core/final_services.py || fail "protected business/inventory logic changed"
# Pin both exact approved warning-only files. This prevents a later
# unreviewed change to stock quantities, valuation, or HTML from passing this
# release simply because inventory_v20.py is now allowlisted.
test "$(git hash-object core/inventory_v20.py)" = "2363028c157e0ed95b41559dfffa94a98f9010d2" || fail "inventory source does not match approved zero/under-ten warning-only revision"
test "$(git hash-object templates/core/inventory_v19.html)" = "ee2171ef85a8be431da59824b56b438c5ad4e05c" || fail "inventory HTML does not match approved warning-only presentation revision"

# V123 only registers one new model; all existing model definitions untouched.
python3 - "$BASE" <<'PY'
import pathlib, subprocess, sys
original=subprocess.check_output(["git","show",f"{sys.argv[1]}:core/models.py"])
current=pathlib.Path("core/models.py").read_bytes()
expected=b"\n\n# Color-scoped material stock use, independent of finished-goods deliveries.\nfrom .material_color_models_v123 import MaterialReportColorUse  # noqa: E402,F401\n"
if current != original+expected:
    raise SystemExit("FAILED: models.py changed beyond V123 isolated registration")
PY
MIGRATION_CHANGED=$(git diff --name-only "$BASE"..HEAD -- core/migrations)
test "$MIGRATION_CHANGED" = "core/migrations/0021_material_color_use_v123.py" || fail "Unexpected DB schema changes"

echo "=== PRODUCTION PRECHECK / BACKUP ==="
docker compose config -q || fail "compose config error"
docker compose ps --status running web | grep -q web || fail "live web container not running"
test -s .env || fail ".env missing"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v123-material-color-transfer-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
test -s "$BACKUP" || fail "backup is empty"
echo "BACKUP=$BACKUP"

HASH_CODE='from hashlib import sha256
from django.apps import apps
names=["StockBalance","InventoryMovement","RawMaterialStock","MaterialReportBlock","MaterialReportOutputApplied","MaterialReportOutputLocation","BusinessPayment","AccountEntry","SaleLine","ProductCode","ProductSize","ExcelManualRow","MaterialReportConsumption"]
for name in names:
 m=apps.get_model("core",name)
 cols=[f.attname for f in m._meta.concrete_fields]
 h=sha256()
 for row in m.objects.order_by("pk").values_list(*cols):
  h.update(repr(row).encode());h.update(b"\\n")
 print(name+"="+h.hexdigest())'
# One shared regex: both running-service and candidate-image checks must
# produce an identical, ordered list of protected ERP model hashes.
SNAPSHOT_REGEX='^(StockBalance|InventoryMovement|RawMaterialStock|MaterialReportBlock|MaterialReportOutputApplied|MaterialReportOutputLocation|BusinessPayment|AccountEntry|SaleLine|ProductCode|ProductSize|ExcelManualRow|MaterialReportConsumption)='
snapshot_live(){ docker compose exec -T web python manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E "$SNAPSHOT_REGEX"; }
snapshot_image(){ docker compose run --rm --entrypoint python web manage.py shell -c "$HASH_CODE" 2>/dev/null | grep -E "$SNAPSHOT_REGEX"; }
PRE=$(snapshot_live) || fail "PRE snapshot failed"
echo "$PRE"

echo "=== READ-ONLY BUILD AND TESTS ==="
docker compose build web || fail "web build failed"
docker compose run --rm --entrypoint python web -m compileall -q core/material_report_v92.py core/material_report_v23.py core/material_report_v20.py core/material_color_apply_v123.py core/material_color_models_v123.py core/inventory_transfer_v123.py core/inventory_operations_v16.py core/migrations/0021_material_color_use_v123.py core/management/commands/check_material_transfer_v123.py core/management/commands/check_inventory_alert_v123.py core/inventory_v20.py core/test_material_color_v123.py || fail "Python syntax check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected database schema migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django project check failed"
docker compose run --rm --entrypoint python web manage.py showmigrations core | grep -Eq '\[X\] 0020_novani_wholesale' || fail "V119 wholesale migration not applied; deploy earlier approved version first"
# V121 account repair must be reviewed/finished separately. Never change it
# as a side effect of a materials report-only release.
REPAIR_AUDIT=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121) || fail "financial state preview failed"
echo "$REPAIR_AUDIT"
printf '%s\n' "$REPAIR_AUDIT" | grep -qx 'PEDRAM_REPAIR_GROSS=0' || fail "V121 Pedram repair still pending; run approved V121 recovery before V123"

echo "=== V123 ISOLATED SCHEMA MIGRATION ==="
docker compose run --rm --entrypoint python web manage.py migrate core 0021_material_color_use_v123 --noinput || fail "V123 isolated color-consumption migration failed"
docker compose run --rm --entrypoint python web manage.py check_material_transfer_v123 || fail "V123 material/inventory read-only audit failed"
docker compose run --rm --entrypoint python web manage.py check_inventory_alert_v123 || fail "V123 inventory warning threshold verification failed"

docker compose run --rm --entrypoint python web manage.py check_material_net_v122 || fail "V122 net/month+carryover verification failed"
docker compose run --rm --entrypoint python web manage.py check_material_summary_box_grid_v110 || fail "V110+V118 UI check failed"
docker compose run --rm --entrypoint python web manage.py check_fabric_roll_count_v116 || fail "V118 fabric roll/weight check failed"
docker compose run --rm --entrypoint python web manage.py check_ui_rail_report_v116 || fail "sidebar regression failed"
docker compose run --rm --entrypoint python web manage.py check_wholesale_v119 || fail "wholesale accounting regression failed"
docker compose run --rm --entrypoint python web manage.py check_production_unit_cost_v113 || fail "calculator regression failed"
PROJECTED=$(snapshot_image) || fail "PROJECTED snapshot failed"
test "$PRE" = "$PROJECTED" || { echo "$PROJECTED"; fail "business data changed during image preflight"; }

test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed"
echo "=== RECREATE WEB ONLY ==="
docker compose up -d --no-deps --force-recreate web || fail "web restart failed"
sleep 6
docker compose exec -T web python manage.py check_material_transfer_v123 || fail "live V123 audit failed"
docker compose exec -T web python manage.py check_inventory_alert_v123 || fail "live V123 warning threshold verification failed"
docker compose exec -T web python manage.py check_material_net_v122 || fail "live V122 verification failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110 report regression failed"
docker compose exec -T web python manage.py check_fabric_roll_count_v116 || fail "live V118 fabric regression failed"
docker compose exec -T web python manage.py check_wholesale_v119 || fail "live V119 finance regression failed"
FINAL=$(snapshot_live) || fail "FINAL snapshot failed"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business data changed during deployment"; }
test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed during deployment"
echo "SUCCESS: V123 MATERIAL COLORS + BIDIRECTIONAL STOCK TRANSFER DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
