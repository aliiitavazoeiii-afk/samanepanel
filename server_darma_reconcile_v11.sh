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
BACKUP="backups/before-darma-reconcile-v11-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "database backup failed"
[ -s "$BACKUP" ] || fail "backup file is empty"
echo "BACKUP OK: $BACKUP"

step "3) BUILD FRESH WEB"
docker compose build web || fail "Docker build failed"

step "4) PREFLIGHT"
docker compose run --rm --entrypoint sh web -c 'python manage.py makemigrations --check --dry-run && python manage.py check && python manage.py check_excel_web && python manage.py check_finance_flow_v9' || fail "preflight failed"

step "5) DARMA RECONCILE DRY RUN"
docker compose run --rm --entrypoint sh web -c 'python manage.py reconcile_darma_excel_v11' || fail "Darma reconcile dry run failed"

step "6) APPLY EXACT EXCEL DELTAS"
docker compose run --rm --entrypoint sh web -c 'python manage.py reconcile_darma_excel_v11 --apply' || fail "Darma reconcile apply failed"

step "7) VERIFY DARMA QUANTITY + VALUE"
docker compose run --rm --entrypoint sh web -c 'python manage.py shell -c "from django.db.models import Sum; from core.models import Brand,StockBalance,InventoryModelCost; b=Brand.objects.get(name=\"دارما\"); rows=StockBalance.objects.filter(brand=b).values(\"color_id\",\"size_id\").annotate(q=Sum(\"qty\")); costs={(x.color_id,x.size_id):int(x.unit_cost or 0) for x in InventoryModelCost.objects.filter(brand=b)}; qty=sum(int(r[\"q\"] or 0) for r in rows); value=sum(int(r[\"q\"] or 0)*costs.get((r[\"color_id\"],r[\"size_id\"]),0) for r in rows); print(\"DARMA TOTAL QTY   =\",qty); print(\"DARMA TOTAL VALUE =\",value); assert qty==14311, qty; assert value==872971000, value; print(\"DARMA EXCEL TOTAL VERIFIED\")"' || fail "Darma final value verification failed"

step "8) RECREATE LIVE WEB"
docker compose up -d --force-recreate web || fail "could not recreate web"
docker compose restart caddy || fail "could not restart caddy"

step "9) CAPITAL AUDIT"
docker compose exec -T web python manage.py capital_audit_v9 || fail "capital audit failed"

echo ""
echo "======================================"
echo "SUCCESS: DARMA INVENTORY V11 RECONCILED"
echo "Darma target: 14,311 pcs / 872,971,000 toman"
echo "Backup: $BACKUP"
echo "Daily Excel uploads are now protected by a stock-total invariant."
echo "======================================"
