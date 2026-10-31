#!/bin/sh
set -eu
cd /opt/darma-general

fail(){ echo ""; echo "======================================"; echo "FAILED: $1"; echo "======================================"; exit 1; }
step(){ echo ""; echo "======================================"; echo "$1"; echo "======================================"; }

[ -f .env ] || fail ".env not found"

set_env(){
  key="$1"
  value="$2"
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN{done=0}
    $0 ~ "^" k "=" {print k "=" v; done=1; next}
    {print}
    END{if(!done) print k "=" v}
  ' .env > "$tmp"
  cat "$tmp" > .env
  rm -f "$tmp"
}

load_env(){
  set -a
  . ./.env || fail "could not load .env"
  set +a
}

load_env

step "1) START DATABASE"
docker compose up -d db || fail "database start failed"
i=1
while [ "$i" -le 30 ]; do
  docker compose exec -T db pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1 && break
  [ "$i" -eq 30 ] && fail "PostgreSQL did not become ready"
  sleep 1
  i=$((i+1))
done

step "2) REQUIRE V19 LIVE"
if ! docker compose exec -T web python manage.py check_v19_features >/dev/null 2>&1; then
  fail "V19 is not live. First deploy server_saleonly_anbaresh_novani_v19.sh, then rerun this script."
fi

step "3) BACKUP + BEFORE STATE"
mkdir -p backups
BACKUP="backups/before-telegram-inventory-bot-v20-$(date +%Y%m%d-%H%M%S).sql"
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP" || fail "backup failed"
[ -s "$BACKUP" ] || fail "backup is empty"
echo "BACKUP: $BACKUP"

CAP_BEFORE=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
[ -n "$CAP_BEFORE" ] || fail "could not read capital before"
DARMA_BEFORE=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ -n "$DARMA_BEFORE" ] || fail "could not read Darma stock before"
echo "CAPITAL BEFORE = $CAP_BEFORE"
echo "DARMA QTY BEFORE = $DARMA_BEFORE"

step "4) TELEGRAM TOKEN"
TOKEN="${TELEGRAM_BOT_TOKEN:-}"
if [ -z "$TOKEN" ]; then
  printf "BotFather token را وارد کن: "
  if [ -t 0 ]; then
    stty -echo 2>/dev/null || true
    IFS= read -r TOKEN
    stty echo 2>/dev/null || true
    printf "\n"
  else
    IFS= read -r TOKEN
  fi
  [ -n "$TOKEN" ] || fail "Telegram bot token is empty"
  set_env TELEGRAM_BOT_TOKEN "$TOKEN"
fi
set_env TELEGRAM_HOME_MIN "30"
set_env TELEGRAM_TOTAL_MIN "60"
set_env TELEGRAM_ALERT_TIMEZONE "Asia/Tehran"
chmod 600 .env 2>/dev/null || true
load_env

step "5) BUILD + PREFLIGHT"
docker compose -f compose.yml -f compose.telegram.yml build web bot || fail "web/bot image build failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check || fail "Django check failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_telegram_bot_v20 --network || fail "Telegram preflight failed"
docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python web manage.py makemigrations --check --dry-run || fail "model/migration drift detected"

step "6) LOCK BOT TO YOUR TELEGRAM ACCOUNT"
USER_ID="${TELEGRAM_ALLOWED_USER_ID:-}"
case "$USER_ID" in
  ''|*[!0-9]*|0) USER_ID="" ;;
esac

if [ -z "$USER_ID" ]; then
  docker compose -f compose.yml -f compose.telegram.yml up -d --force-recreate bot || fail "bootstrap bot start failed"
  BOT_LINE=$(docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_telegram_bot_v20 --network 2>/dev/null | grep 'TELEGRAM getMe OK' | tail -1 || true)
  BOT_NAME=$(printf '%s' "$BOT_LINE" | sed -n 's/.*@/@/p')
  echo ""
  echo "ربات ${BOT_NAME:-تلگرام} را باز کن و پیام /whoami را بفرست."
  echo "ربات یک Telegram User ID بهت می‌دهد."
  printf "آن عدد را اینجا Paste کن و Enter بزن: "
  IFS= read -r USER_ID
  case "$USER_ID" in
    ''|*[!0-9]*|0) fail "Telegram User ID must be a positive number" ;;
  esac
fi

# v20 is intentionally private to one Telegram account. Clear any old plural
# allow-list so it cannot override the selected singular ID.
set_env TELEGRAM_ALLOWED_USER_ID "$USER_ID"
set_env TELEGRAM_ALLOWED_USER_IDS ""
load_env

docker compose -f compose.yml -f compose.telegram.yml run --rm --entrypoint python bot manage.py check_telegram_bot_v20 --network || fail "locked Telegram preflight failed"

step "7) START LIVE WEB + BOT"
docker compose -f compose.yml -f compose.telegram.yml up -d --force-recreate web bot || fail "web/bot start failed"
docker compose restart caddy || fail "caddy restart failed"
i=1
while [ "$i" -le 20 ]; do
  docker compose -f compose.yml -f compose.telegram.yml ps --status running bot 2>/dev/null | grep -q bot && break
  [ "$i" -eq 20 ] && { docker compose -f compose.yml -f compose.telegram.yml logs --tail=100 bot || true; fail "bot did not stay running"; }
  sleep 1
  i=$((i+1))
done

step "8) SEND TEST MESSAGE"
docker compose -f compose.yml -f compose.telegram.yml exec -T bot python manage.py shell -c 'import os; from core.telegram_inventory_bot_v20 import TelegramAPI,allowed_user_ids,main_menu; api=TelegramAPI(os.getenv("TELEGRAM_BOT_TOKEN")); [api.send(uid,"✅ ربات انبار دارما فعال شد.\nهشدار خودکار: بعد از صورت روزانه + ساعت ۹ صبح.",main_menu()) for uid in allowed_user_ids()]' || fail "test Telegram message failed"

step "9) VERIFY BUSINESS DATA UNCHANGED"
CAP_AFTER=$(docker compose exec -T web python manage.py capital_audit_v9 | awk -F'= ' '/CAPITAL TOTAL/{gsub(/[[:space:]]/,"",$2);print $2}' | tail -1)
DARMA_AFTER=$(docker compose exec -T web python manage.py shell -c 'from django.db.models import Sum; from core.models import Brand,StockBalance; b=Brand.objects.get(name="دارما"); print(int(StockBalance.objects.filter(brand=b).aggregate(v=Sum("qty"))["v"] or 0))' 2>/dev/null | tail -1)
[ "$CAP_BEFORE" = "$CAP_AFTER" ] || fail "capital changed during bot deployment: before=$CAP_BEFORE after=$CAP_AFTER"
[ "$DARMA_BEFORE" = "$DARMA_AFTER" ] || fail "Darma stock changed during bot deployment: before=$DARMA_BEFORE after=$DARMA_AFTER"

step "10) FINAL STATUS"
docker compose -f compose.yml -f compose.telegram.yml ps web bot

echo ""
echo "======================================"
echo "SUCCESS: TELEGRAM INVENTORY BOT V20 IS RUNNING"
echo "Backup: $BACKUP"
echo "Capital unchanged: $CAP_AFTER"
echo "Darma stock unchanged: $DARMA_AFTER"
echo "HOME alert: below 30"
echo "PRODUCTION alert: total <= 60"
echo "AUTO ALERTS: once after daily report + once daily at 09:00 Asia/Tehran"
echo "======================================"
