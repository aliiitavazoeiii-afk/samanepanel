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

step "2) BACKUP CURRENT DATABASE"
mkdir -p backups || fail "could not create backup directory"
BACKUP="backups/before-material-apply-v13-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "4) CHECK MODEL / MIGRATION DRIFT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run' || fail "model/migration drift detected"
echo "MIGRATION FILES MATCH MODELS"

step "5) MIGRATE"
docker compose run --rm --entrypoint sh web -c 'python manage.py migrate --noinput' || fail "migration failed"

step "6) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py check && python manage.py check_excel_web && python manage.py check_finance_flow_v9 && python manage.py check_material_flow_v13' || fail "preflight failed"
echo "PREFLIGHT OK"

step "7) VERIFY V13 RUNTIME"
docker compose run --rm --no-deps --entrypoint sh web -c 'python manage.py shell -c "
from django.urls import reverse, resolve
from django.template.loader import get_template
assert resolve(reverse(\"material_block_save\", args=[1])).func.__module__ == \"core.material_report_v13\"
assert resolve(reverse(\"material_block_apply\", args=[1])).func.__module__ == \"core.material_report_v13\"
assert resolve(reverse(\"material_block_unapply\", args=[1])).func.__module__ == \"core.material_report_v13\"
assert resolve(reverse(\"payment_add\")).func.__module__ == \"core.business_tools_v13\"
get_template(\"core/material_report_v13.html\")
get_template(\"core/payments_v13.html\")
print(\"MATERIAL V13 RUNTIME CHECK OK\")
"' || fail "v13 runtime verification failed"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "9) SHOW CURRENT APPLIED MATERIAL REPORTS"
docker compose exec -T web python manage.py shell -c '
from core.models import MaterialReportBlock
rows=[]
for b in MaterialReportBlock.objects.order_by("-date","-id"):
    n=b.stock_consumptions.count()
    if n:
        rows.append((b.id, str(b.date), b.title or "صورت مواد اولیه", n))
print("APPLIED MATERIAL REPORTS =", len(rows))
for r in rows[:20]: print("APPLIED BLOCK:", *r)
' || fail "could not inspect applied material reports"

step "10) CAPITAL AUDIT"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit failed"

step "11) STATUS"
docker compose ps

echo ""
echo "======================================"
echo "SUCCESS: MATERIAL APPLY + PURCHASES V13 DEPLOYED"
echo "Backup: $BACKUP"
echo "If the current report was auto-consumed before v13, open it and click: برگرداندن اثر موجودی خیاط"
echo "======================================"
