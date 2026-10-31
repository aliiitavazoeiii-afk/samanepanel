#!/bin/sh
set -eu
cd /opt/darma-general
fail(){ echo "FAILED: $1"; exit 1; }
export COMPOSE_IGNORE_ORPHANS=1
BASE=1dec0ba87d16f23e09be5f9ae981577bf89f09e0

echo "=== V124 DYNAMIC DARMA MATERIAL PURCHASE COLORS ==="
test "$(git branch --show-current)" = "v124-dynamic-payment-fabric-colors" || fail "wrong branch"
git cat-file -e "$BASE^{commit}" || fail "V123 parent commit missing"
git diff --quiet -- . ':(exclude)Caddyfile' || fail "other tracked local changes exist"
git diff --cached --quiet -- . ':(exclude)Caddyfile' || fail "other staged local changes exist"
git diff --quiet "$BASE"..HEAD -- Caddyfile || fail "V124 must not change Caddyfile"
test -f Caddyfile || fail "Caddyfile missing"
CADDY_BEFORE=$(sha256sum Caddyfile | awk '{print $1}')
CHANGED=$(git diff --name-only "$BASE"..HEAD)
echo "$CHANGED"
for f in $CHANGED; do
  case "$f" in
    .github/workflows/check-payment-colors-v124.yml|PROJECT_HANDOFF_CURRENT.md|core/business_tools_v91.py|core/management/commands/check_payment_colors_v124.py|core/material_payment_colors_v124.py|core/material_purchase_v13.py|docs/PROJECT_CONTEXT/72_PAYMENT_REGISTERED_COLORS_V124.md|docs/PROJECT_CONTEXT/README.md|server_payment_colors_v124.sh) ;;
    *) fail "unexpected V124 file: $f" ;;
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

# Only the three approved payment color source files may modify payment
# behavior. Their pinned blobs lock the price, bank, raw-stock and editing
# formulas until another reviewed deployment updates these checks.
test "$(git hash-object core/material_payment_colors_v124.py)" = "380f7f8c3d4f0aaceba6a1c6685fd094be33c194" || fail "material color helper drift"
test "$(git hash-object core/business_tools_v91.py)" = "245f5dac316b1c6931d26edf84b96c206a6e232d" || fail "payment view drift"
test "$(git hash-object core/material_purchase_v13.py)" = "cac0f262ab3df38c7d92d254469541a93eb5e8e4" || fail "purchase parser drift"
git diff --quiet "$BASE"..HEAD -- core/models.py core/migrations core/material_report_v23.py core/material_flow.py core/material_purchase_v14.py core/material_purchase_v60.py core/business_tools_v62.py core/inventory_v20.py core/inventory_transfer_v123.py core/wholesale_logic_v119.py core/final_services.py templates/core/payments_v22.html templates/core/_payment_edit_v22.html || fail "protected finance, material posting, inventory, or payment template changed"

MIGRATION_CHANGED=$(git diff --name-only "$BASE"..HEAD -- core/migrations)
test -z "$MIGRATION_CHANGED" || fail "V124 must not introduce migrations"

echo "=== PRODUCTION PRECHECK / BACKUP ==="
docker compose config -q || fail "compose config error"
docker compose ps --status running web | grep -q web || fail "live web container not running"
test -s .env || fail ".env missing"
set -a; . ./.env; set +a
mkdir -p backups
BACKUP="backups/before-v124-payment-colors-$(date +%Y%m%d-%H%M%S).sql"
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
# The live server may reach Docker Hub manifest metadata but receive HTTP
# 403 when retrieving Python layers from Docker Hub's CloudFront CDN.
# Never edit the tracked Dockerfile, Docker daemon configuration or Caddyfile.
# If and ONLY if the base-image retrieval fails, try trusted mirrors with a
# temporary equivalent Dockerfile and tag the exact Compose web image.
echo "=== V124 SAFE DOCKER BASE-IMAGE FALLBACK ==="
BUILD_LOG=$(mktemp /tmp/darma-v124-build-log.XXXXXX)
TEMP_DOCKERFILE=$(mktemp /tmp/darma-v124-Dockerfile.XXXXXX)
trap 'rm -f "$BUILD_LOG" "$TEMP_DOCKERFILE"' EXIT
if docker compose build web >"$BUILD_LOG" 2>&1; then
  cat "$BUILD_LOG"
  echo "DOCKER_BASE_IMAGE_SOURCE=docker_hub"
else
  cat "$BUILD_LOG"
  if ! grep -Eq 'failed to resolve source metadata|production.cloudfront.docker.com|unexpected status.*403|403 Forbidden' "$BUILD_LOG"; then
    fail "Docker build failed for a reason other than base-image registry access; current web remains unchanged"
  fi
  test "$(head -n 1 Dockerfile)" = "FROM python:3.12-slim" || fail "unexpected tracked Dockerfile base; refusing mirror substitution"
  WEB_IMAGE=$(docker compose config --format json | python3 -c 'import json,sys; c=json.load(sys.stdin); web=c["services"]["web"]; print(web.get("image") or (c["name"]+"-web"))') || fail "cannot determine Compose web image name"
  test -n "$WEB_IMAGE" || fail "empty Compose web image name"
  MIRROR_OK=0
  for PYTHON_BASE in public.ecr.aws/docker/library/python:3.12-slim mirror.gcr.io/library/python:3.12-slim; do
    echo "TRY_ALTERNATE_PYTHON_BASE=$PYTHON_BASE"
    { printf 'FROM %s\n' "$PYTHON_BASE"; tail -n +2 Dockerfile; } > "$TEMP_DOCKERFILE"
    if docker buildx build --load --progress=plain -f "$TEMP_DOCKERFILE" -t "$WEB_IMAGE" .; then
      MIRROR_OK=1
      echo "DOCKER_BASE_IMAGE_SOURCE=$PYTHON_BASE"
      break
    fi
  done
  test "$MIRROR_OK" = "1" || fail "Docker Hub returned 403 and alternate public registries were also inaccessible; no web restart performed"
fi
docker compose run --rm --entrypoint python web -m compileall -q core/material_report_v92.py core/material_report_v23.py core/material_report_v20.py core/material_color_apply_v123.py core/material_color_models_v123.py core/inventory_transfer_v123.py core/inventory_operations_v16.py core/migrations/0021_material_color_use_v123.py core/management/commands/check_material_transfer_v123.py core/management/commands/check_inventory_alert_v123.py core/material_payment_colors_v124.py core/business_tools_v91.py core/material_purchase_v13.py core/management/commands/check_payment_colors_v124.py core/inventory_v20.py core/test_material_color_v123.py || fail "Python syntax check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "unexpected database schema migration"
docker compose run --rm --entrypoint python web manage.py check || fail "Django project check failed"
docker compose run --rm --entrypoint python web manage.py showmigrations core | grep -Eq '\[X\] 0021_material_color_use_v123' || fail "V123 per-color migration missing; deploy V123 first"
# V121 account repair must be reviewed/finished separately. Never change it
# as a side effect of a materials report-only release.
REPAIR_AUDIT=$(docker compose run --rm --entrypoint python web manage.py repair_pedram_wholesale_v121) || fail "financial state preview failed"
echo "$REPAIR_AUDIT"
printf '%s\n' "$REPAIR_AUDIT" | grep -qx 'PEDRAM_REPAIR_GROSS=0' || fail "V121 Pedram repair still pending; complete approved recovery before V124"

echo "=== V124 NO MIGRATION OR BUSINESS DATA WRITES ==="
docker compose run --rm --entrypoint python web manage.py check_payment_colors_v124 || fail "V124 registered payment colors audit failed"
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
docker compose up -d --no-deps --no-build --force-recreate web || fail "web restart failed"
sleep 6
docker compose exec -T web python manage.py check_payment_colors_v124 || fail "live V124 color validation failed"
docker compose exec -T web python manage.py check_material_transfer_v123 || fail "live V123 audit failed"
docker compose exec -T web python manage.py check_inventory_alert_v123 || fail "live V123 warning threshold verification failed"
docker compose exec -T web python manage.py check_material_net_v122 || fail "live V122 verification failed"
docker compose exec -T web python manage.py check_material_summary_box_grid_v110 || fail "live V110 report regression failed"
docker compose exec -T web python manage.py check_fabric_roll_count_v116 || fail "live V118 fabric regression failed"
docker compose exec -T web python manage.py check_wholesale_v119 || fail "live V119 finance regression failed"
FINAL=$(snapshot_live) || fail "FINAL snapshot failed"
test "$PRE" = "$FINAL" || { echo "$FINAL"; fail "business data changed during deployment"; }
test "$(sha256sum Caddyfile | awk '{print $1}')" = "$CADDY_BEFORE" || fail "Caddyfile changed during deployment"
echo "SUCCESS: V124 DYNAMIC PAYMENT FABRIC COLORS DEPLOYED"
echo "PRE = PROJECTED = FINAL"
echo "BACKUP=$BACKUP"
