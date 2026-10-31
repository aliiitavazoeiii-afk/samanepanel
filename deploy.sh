#!/usr/bin/env bash
set -euo pipefail
DOMAIN="gozaresh.filmjadiid.ir"
REPO="https://github.com/aliiitavazoeiii-afk/darma-general.git"
APP_DIR="/opt/darma-general"

if [ "$(id -u)" -ne 0 ]; then
  echo "این دستور را با root اجرا کن." >&2
  exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl git openssl
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  rm -rf "$APP_DIR"
  git clone "$REPO" "$APP_DIR"
fi
cd "$APP_DIR"

if [ ! -f .env ]; then
  SECRET_KEY=$(openssl rand -hex 32)
  DB_PASSWORD=$(openssl rand -hex 24)
  ADMIN_PASSWORD=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-18)
  cat > .env <<ENV
DEBUG=0
SECRET_KEY=$SECRET_KEY
ALLOWED_HOSTS=$DOMAIN
CSRF_TRUSTED_ORIGINS=https://$DOMAIN
DB_NAME=darma
DB_USER=darma
DB_PASSWORD=$DB_PASSWORD
DB_HOST=db
DB_PORT=5432
APP_ADMIN_USERNAME=ali
APP_ADMIN_PASSWORD=$ADMIN_PASSWORD
ENV
  chmod 600 .env
  echo
  echo "=============================================="
  echo "نام کاربری سایت: ali"
  echo "رمز اولیه سایت: $ADMIN_PASSWORD"
  echo "این رمز را همین الان جایی امن ذخیره کن."
  echo "=============================================="
  echo
fi

docker compose up -d --build

echo
echo "وضعیت سرویس‌ها:"
docker compose ps
echo
echo "سایت: https://$DOMAIN"
echo "اگر DNS درست باشد، Caddy گواهی HTTPS را خودکار می‌گیرد."
