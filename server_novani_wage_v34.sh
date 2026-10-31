#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"
set -a
. ./.env || fail "could not load .env"
set +a

step "1) START DATABASE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "2) FULL DATABASE BACKUP"
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="backups/before-novani-wage-v34-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

step "3) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "4) GENERIC PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"

step "5) SET + VERIFY BUSINESS RULE: 110,000 TOMAN PER 12 PIECES"
RATE_OUT=$(docker compose run --rm --entrypoint python web manage.py shell -c '
from core.models import AppSetting
obj=AppSetting.objects.filter(key="pedram_dozen_wage").first()
print("DOZEN_WAGE_BEFORE=" + (str(obj.value) if obj else "MISSING"))
obj,_=AppSetting.objects.update_or_create(
    key="pedram_dozen_wage",
    defaults={"value":"110000","label":"مزد هر جین پدرام"},
)
print("DOZEN_WAGE_AFTER=" + str(obj.value))
') || fail "could not set dozen wage to 110,000"
echo "$RATE_OUT"
printf '%s\n' "$RATE_OUT" | grep -q '^DOZEN_WAGE_AFTER=110000$' || fail "dozen wage is not 110,000 after update"
docker compose run --rm --entrypoint python web manage.py check_novani_wage_v34 || fail "Novani wage regression check failed"

step "6) DRY-RUN CURRENT MISSING WAGE REPAIR"
DRY=$(docker compose run --rm --entrypoint python web manage.py repair_novani_wage_v34 \
  --expected-pieces 3630 \
  --expected-wage 33275000) || fail "repair dry-run failed; nothing else was changed"
echo "$DRY"
printf '%s\n' "$DRY" | grep -q '^NOVANI_V21_PIECES=3630$' || fail "latest Novani v21 output is not 3630 pieces"
printf '%s\n' "$DRY" | grep -q '^DOZEN_WAGE=110000$' || fail "configured dozen wage is not 110,000"
printf '%s\n' "$DRY" | grep -q '^MISSING_WAGE=33275000$' || fail "calculated missing wage is not 33,275,000"
printf '%s\n' "$DRY" | grep -q '^REPAIR_ALREADY_APPLIED=0$' || fail "this block appears already repaired"
BLOCK_ID=$(printf '%s\n' "$DRY" | awk -F= '/^BLOCK_ID=/{print $2}')
[ -n "$BLOCK_ID" ] || fail "could not determine Novani block id"
echo "TARGET BLOCK = $BLOCK_ID"

step "7) CAPTURE INVENTORY + RAW MATERIALS BEFORE REPAIR"
STATE_BEFORE=$(docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance
from core.report_v5 import _raw_material_context
for name in ["Novani", "دارما"]:
    b=Brand.objects.get(name=name)
    q=int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
    print(f"{name}={q}")
print("RAW=" + str(int(_raw_material_context()["materials_total"])))
' 2>/dev/null) || fail "could not capture state before repair"
echo "$STATE_BEFORE"

step "8) APPLY ONLY MISSING TAILOR WAGE + CORRECT SAVED DELIVERY WAGE"
APPLY=$(docker compose run --rm --entrypoint python web manage.py repair_novani_wage_v34 \
  --block-id "$BLOCK_ID" \
  --expected-pieces 3630 \
  --expected-wage 33275000 \
  --apply) || fail "wage repair failed"
echo "$APPLY"
printf '%s\n' "$APPLY" | grep -q 'SUCCESS: NOVANI MISSING WAGE V34 REPAIRED; INVENTORY UNCHANGED' || fail "repair did not report success"
printf '%s\n' "$APPLY" | grep -q '^BLOCK_DELIVERY_WAGE_AFTER=33275000$' || fail "saved delivery wage was not corrected to 33,275,000"

step "9) VERIFY INVENTORY + RAW MATERIALS DID NOT MOVE"
STATE_AFTER=$(docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.models import Brand, StockBalance
from core.report_v5 import _raw_material_context
for name in ["Novani", "دارما"]:
    b=Brand.objects.get(name=name)
    q=int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
    print(f"{name}={q}")
print("RAW=" + str(int(_raw_material_context()["materials_total"])))
' 2>/dev/null) || fail "could not capture state after repair"
echo "$STATE_AFTER"
[ "$STATE_BEFORE" = "$STATE_AFTER" ] || fail "inventory/raw materials changed during wage-only repair"

step "10) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_novani_wage_v34 || fail "live Novani wage check failed"

step "11) FINAL STATE"
docker compose exec -T web python manage.py shell -c "
from core.material_report_v14 import _tailor_row
from core.models import AppSetting, MaterialReportBlock
r=_tailor_row(create=False)
b=MaterialReportBlock.objects.get(id=${BLOCK_ID})
print('DOZEN_WAGE=', AppSetting.objects.get(key='pedram_dozen_wage').value)
print('DELIVERY_WAGE=', int(b.delivery_wage or 0))
print('TAILOR_BALANCE=', int(r.amount or 0) if r else 0)
print('REPAIR_MARKER=', AppSetting.objects.filter(key='novani_wage_repair_v34_block_${BLOCK_ID}', value='1').exists())
"

echo ""
echo "======================================"
echo "SUCCESS: NOVANI DELIVERY WAGE V34 DEPLOYED + CURRENT BLOCK REPAIRED"
echo "Backup: $BACKUP"
echo "Current Novani block: $BLOCK_ID"
echo "Dozen wage: 110,000 toman per 12 pieces"
echo "Delivered pieces: 3,630"
echo "Missing wage deducted: 33,275,000"
echo "Saved delivery wage corrected: 33,275,000"
echo "Inventory/raw materials during repair: unchanged"
echo "Future Novani wage: based only on newly delivered pieces"
echo "Cut quantity does not create tailor-balance wage"
echo "======================================"
