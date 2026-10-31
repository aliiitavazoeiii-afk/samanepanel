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
BACKUP="backups/before-novani-output-edit-v35-${STAMP}.sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "database backup is empty"
echo "BACKUP = $BACKUP"

snapshot_live() {
  docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.material_report_v14 import _tailor_row
from core.models import Brand, ExcelManualRow, ExcelManualSetting, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
t=_tailor_row(create=False)
print(f"CAPITAL={capital}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"RAW={raw}")
print(f"TAILOR={int(t.amount or 0) if t else 0}")
' 2>/dev/null
}

step "3) CAPTURE BUSINESS VALUES BEFORE DEPLOY"
LIVE=$(snapshot_live) || fail "could not read live business values"
echo "$LIVE"

step "4) BUILD LATEST WEB IMAGE"
docker compose build web || fail "web build failed"

step "5) FORCE BUSINESS WAGE RULE TO 110,000 PER DOZEN"
docker compose run --rm --entrypoint python web manage.py shell -c '
from core.models import AppSetting
AppSetting.objects.update_or_create(
    key="pedram_dozen_wage",
    defaults={"value":"110000", "label":"مزد هر جین پدرام"},
)
print("DOZEN_WAGE_SETTING=110000")
' || fail "could not set dozen wage to 110000"

step "6) PREFLIGHT"
docker compose run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "migration drift detected"
docker compose run --rm --entrypoint python web manage.py check || fail "Django check failed"
docker compose run --rm --entrypoint python web manage.py check_novani_output_edit_v35 || fail "Novani output v35 regression check failed"
docker compose run --rm --entrypoint python web -c '
from pathlib import Path
p=Path("/app/templates/core/material_report_v35.html")
t=p.read_text(encoding="utf-8")
assert "تاریخ تحویل" not in t
for token in ["برش", "کسری / مازاد", "جمع کل کارهای تحویل‌گرفته‌شده", "همگام‌سازی تحویل و موجودی"]:
    assert token in t, token
print("NOVANI OUTPUT V35 TEMPLATE CHECK OK")
' || fail "template preflight failed"

step "7) VERIFY DEPLOY/PREFLIGHT DID NOT CHANGE BUSINESS VALUES"
NEW=$(docker compose run --rm --entrypoint python web manage.py shell -c '
from django.db.models import Sum
from core.finance_excel_v9 import digikala_receivable_total
from core.inventory_valuation_v17 import finished_inventory_value_v17
from core.material_report_v14 import _tailor_row
from core.models import Brand, ExcelManualRow, ExcelManualSetting, StockBalance
from core.report_v5 import _raw_material_context

def bqty(name):
    b=Brand.objects.get(name=name)
    return int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0)
rows=ExcelManualRow.objects.filter(active=True)
accounts=sum(int(x.amount or 0) for x in rows.filter(section__in=[ExcelManualRow.ACCOUNTS,ExcelManualRow.PERSONS]))
assets=sum(int(x.amount or 0) for x in rows.filter(section=ExcelManualRow.ASSETS))
finished=int(finished_inventory_value_v17())
raw=int(_raw_material_context()["materials_total"])
digi=int(digikala_receivable_total())
debt=int(ExcelManualSetting.objects.filter(key="takvin_debt").values_list("value",flat=True).first() or 0)
capital=accounts+assets+finished+raw+digi-debt
t=_tailor_row(create=False)
print(f"CAPITAL={capital}")
print(f"DARMA={bqty(chr(1583)+chr(1575)+chr(1585)+chr(1605)+chr(1575))}")
print(f"NOVANI={bqty(chr(78)+chr(111)+chr(118)+chr(97)+chr(110)+chr(105))}")
print(f"RAW={raw}")
print(f"TAILOR={int(t.amount or 0) if t else 0}")
' 2>/dev/null) || fail "could not read post-preflight business values"
echo "$NEW"
[ "$LIVE" = "$NEW" ] || fail "business values changed during deploy/preflight"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "web recreate failed"
docker compose restart caddy || fail "caddy restart failed"
sleep 4
docker compose exec -T web python manage.py check || fail "live Django check failed"
docker compose exec -T web python manage.py check_novani_output_edit_v35 || fail "live Novani output v35 check failed"

step "9) CURRENT NOVANI BLOCK STATUS — READ ONLY"
docker compose exec -T web python manage.py shell -c '
from django.db.models import Sum
from core.models import AppSetting, Brand, MaterialReportBlock
b=Brand.objects.get(name="Novani")
block=(MaterialReportBlock.objects.filter(brand=b, output_applications__quantity__gt=0).distinct().order_by("-id").first())
if not block:
    print("CURRENT_BLOCK=NONE")
else:
    applied=int(block.output_applications.aggregate(v=Sum("quantity"))["v"] or 0)
    entered=0
    for values in (block.output_data or {}).values():
        for key,value in (values or {}).items():
            if key=="delivery_date": continue
            try: entered += max(0,int(value or 0))
            except Exception: pass
    marker=AppSetting.objects.filter(key=f"novani_wage_repair_v34_block_{block.id}", value="1").exists()
    print(f"CURRENT_BLOCK={block.id}")
    print(f"CURRENT_APPLIED={applied}")
    print(f"CURRENT_ENTERED={entered}")
    print(f"V34_WAGE_REPAIR_MARKER={1 if marker else 0}")
'

echo ""
echo "======================================"
echo "SUCCESS: NOVANI EDITABLE DELIVERY V35 DEPLOYED"
echo "Backup: $BACKUP"
echo "Novani applied delivery can now be reduced or cleared"
echo "Reduction removes the same Novani stock and returns its wage"
echo "Darma behavior is unchanged"
echo "Delivery-date column removed"
echo "Cut + shortage/surplus columns added"
echo "Grand delivered total added"
echo "Dozen wage rule = 110,000 per 12 pieces"
echo "======================================"
