#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then
  echo 'Run this installer as root.' >&2
  exit 1
fi

for cmd in docker git openssl curl python3 ss; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "Missing required command: $cmd" >&2; exit 1; }
done
docker compose version >/dev/null 2>&1 || { echo 'Docker Compose plugin is required.' >&2; exit 1; }

APP=/opt/dia-darma-fresh
REPO=https://github.com/aliiitavazoeiii-afk/samanepanel.git
BRANCH=dia-darma-fresh

if [ -e "$APP" ]; then
  echo "ABORT: $APP already exists. No files were modified." >&2
  exit 1
fi
if ss -H -ltn '( sport = :18081 )' | grep -q .; then
  echo 'ABORT: port 18081 is occupied.' >&2
  exit 1
fi

git ls-remote --exit-code --heads "$REPO" "$BRANCH" >/dev/null || {
  echo "ABORT: branch $BRANCH not yet present in samanepanel." >&2
  exit 1
}

git clone --single-branch --branch "$BRANCH" "$REPO" "$APP"
cd "$APP"

test -f core/models.py
test -f core/urls.py
test -f compose.fresh.yml
test -f deploy/darma-fresh/runtime_entrypoint.sh

umask 077
DJANGO_KEY="$(openssl rand -hex 32)"
DB_SECRET="$(openssl rand -hex 24)"
ADMIN_SECRET="$(openssl rand -base64 24 | tr -d '\n')"
cat > .env <<EOF
DEBUG=0
SECRET_KEY=$DJANGO_KEY
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://127.0.0.1:18081,http://localhost:18081
DB_NAME=dia_darma_fresh
DB_USER=dia_darma_fresh
DB_PASSWORD=$DB_SECRET
DB_HOST=db
DB_PORT=5432
APP_ADMIN_USERNAME=diaadmin_fresh
APP_ADMIN_PASSWORD=$ADMIN_SECRET
DIA_DARMA_SSH_ONLY=1
DIGIKALA_ZERO_GUARD_WRITE_ENABLED=0
EOF
chmod 600 .env

docker compose -f compose.fresh.yml config --quiet
docker compose -f compose.fresh.yml up -d --build

# Compose marks a web container started before its entrypoint finishes
# Django migrations. Wait for Gunicorn /login/ before touching business tables.
initial_ready=0
for i in $(seq 1 60); do
  code="$(curl --max-time 3 -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18081/login/ || true)"
  if [ "$code" = "200" ]; then initial_ready=1; break; fi
  sleep 2
done
if [ "$initial_ready" -ne 1 ]; then
  echo "ERROR: Django startup/migrations did not complete." >&2
  docker compose -f compose.fresh.yml logs --tail=100 web
  exit 1
fi

# Verify migrations, then create only two generic location keys needed by
# existing Darma inventory screens. No brand, account, stock or sale data.
docker compose -f compose.fresh.yml exec -T web python manage.py check
docker compose -f compose.fresh.yml exec -T web python manage.py shell -c \
'from core.models import StockLocation; StockLocation.objects.get_or_create(key="home", defaults={"title":"انبار اصلی"}); StockLocation.objects.get_or_create(key="khorshid", defaults={"title":"انبار دوم"}); print("GENERIC_STOCK_LOCATIONS_OK")'

docker compose -f compose.fresh.yml exec -T web python manage.py shell -c \
'from core.models import Brand,ProductCode,SaleDay,SaleLine,StockBalance,Account,Color,WholesaleCustomer; counts={"brands":Brand.objects.count(),"products":ProductCode.objects.count(),"days":SaleDay.objects.count(),"sales":SaleLine.objects.count(),"stocks":StockBalance.objects.count(),"accounts":Account.objects.count(),"colors":Color.objects.count(),"customers":WholesaleCustomer.objects.count()}; print("FRESH_BUSINESS_COUNTS",counts); assert all(v == 0 for v in counts.values()), "Unexpected business data in fresh database"'

HTTP_CODE=''
for i in $(seq 1 30); do
  HTTP_CODE="$(curl --max-time 3 --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:18081/login/ || true)"
  [ "$HTTP_CODE" = "200" ] && break
  sleep 2
done
[ "$HTTP_CODE" = "200" ] || { echo "Login health failed (HTTP $HTTP_CODE)." >&2; exit 1; }

echo ''
echo '=============================================='
echo 'DIA DARMA FRESH INSTALL SUCCESS'
echo 'Address via SSH tunnel: http://127.0.0.1:18081/login/'
echo 'Username: diaadmin_fresh'
printf 'Initial password: %s\n' "$ADMIN_SECRET"
echo "Install directory: $APP"
echo "Git branch: $(git branch --show-current)"
echo 'Original Dia Gallery and Darma instances not modified.'
echo '=============================================='
docker compose -f compose.fresh.yml ps
