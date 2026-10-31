#!/usr/bin/env bash
# Safe repair/verification for the isolated Dia Darma fresh installation.
# Never removes databases, volumes or other Compose projects.
set -euo pipefail
APP="/opt/dia-darma-fresh"
COMPOSE="compose.fresh.yml"
if [ "$(id -u)" -ne 0 ]; then echo "Run as root." >&2; exit 1; fi
if [ ! -f "$APP/$COMPOSE" ] || [ ! -f "$APP/.env" ] || [ ! -d "$APP/.git" ]; then
  echo "ABORT: fresh installation not found. Original site untouched." >&2; exit 1
fi
cd "$APP"
if [ "$(git branch --show-current)" != "dia-darma-fresh" ]; then
  echo "ABORT: unexpected Git branch. Original site untouched." >&2; exit 1
fi
docker compose -f "$COMPOSE" config --quiet

echo "=== Existing fresh-instance containers ==="
docker compose -f "$COMPOSE" ps

echo "=== Stop only the new panel's web container, never the DB or main site ==="
docker compose -f "$COMPOSE" stop web

echo "=== Apply outstanding migrations on the isolated database ==="
if ! docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py migrate --noinput; then
  echo "ERROR: database migrations failed. No reset performed." >&2
  echo "Inspect the output and send it for diagnosis; original site untouched." >&2
  exit 1
fi

echo "=== Check Django model/migration integrity ==="
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py check
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py makemigrations --check --dry-run

echo "=== Verify all wholesale database tables and zero business rows ==="
docker compose -f "$COMPOSE" run --rm --no-deps --entrypoint python web manage.py shell -c '
from django.db import connection
from core.models import Brand, ProductCode, SaleDay, SaleLine, StockBalance, Account, Color, WholesaleCustomer, WholesaleInvoice, WholesaleInvoiceLine, WholesaleReceipt
expected = ("core_wholesalecustomer", "core_wholesaleinvoice", "core_wholesaleinvoiceline", "core_wholesalereceipt")
present = set(connection.introspection.table_names())
missing = [x for x in expected if x not in present]
print("WHOLESALE_TABLES_MISSING", missing)
assert not missing, "Migration tables are incomplete"
counts = {
 "brands": Brand.objects.count(), "products": ProductCode.objects.count(),
 "days": SaleDay.objects.count(), "sales": SaleLine.objects.count(),
 "stocks": StockBalance.objects.count(), "accounts": Account.objects.count(),
 "colors": Color.objects.count(), "customers": WholesaleCustomer.objects.count(),
 "invoices": WholesaleInvoice.objects.count(), "invoice_lines": WholesaleInvoiceLine.objects.count(),
 "receipts": WholesaleReceipt.objects.count()
}
print("FRESH_BUSINESS_COUNTS", counts)
assert all(v == 0 for v in counts.values()), "Unexpected business data; stop before further action"
'

echo "=== Restart only isolated web ==="
docker compose -f "$COMPOSE" up -d --no-deps web

echo "=== Wait for the login endpoint to respond ==="
ready=0
for _ in $(seq 1 45); do
  code="$(curl --max-time 3 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/login/ || true)"
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 2
done
if [ "$ready" -ne 1 ]; then
  echo "ERROR: panel did not return HTTP 200 on port 18081." >&2
  docker compose -f "$COMPOSE" logs --tail=80 web
  exit 1
fi
echo "DIA_DARMA_FRESH_REPAIR_OK"
echo "Server-local login: http://127.0.0.1:18081/login/"
docker compose -f "$COMPOSE" ps
