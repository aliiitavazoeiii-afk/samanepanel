#!/usr/bin/env bash
# Enable forosh.filmjadiid.ir on the existing Dia Gallery Caddy without
# overwriting its container, site block or database.
set -Eeuo pipefail

DOMAIN=forosh.filmjadiid.ir
FRESH=/opt/dia-darma-fresh
DIA=/opt/dia-gallery
COMPOSE=compose.fresh.yml
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || fail 'Run as root'
for bin in docker git python3 curl openssl; do
  command -v "$bin" >/dev/null || fail "Missing: $bin"
done
docker compose version >/dev/null || fail 'Docker Compose plugin missing'
[ -f "$FRESH/.env" ] && [ -f "$FRESH/$COMPOSE" ] || fail 'Fresh panel installation not found'
[ -f "$DIA/Caddyfile" ] || fail 'Dia Gallery Caddyfile not found: /opt/dia-gallery/Caddyfile'

# Inspect the live Caddy container and require the exact known bind mount.
CADDY_ID="$(docker ps -q --filter label=com.docker.compose.project=dia-gallery --filter label=com.docker.compose.service=caddy)"
[ -n "$CADDY_ID" ] && [ "$(printf '%s\n' "$CADDY_ID" | wc -l)" -eq 1 ] || fail 'Expected exactly one running Dia Gallery Caddy service'
MOUNT="$(docker inspect "$CADDY_ID" --format '{{range .Mounts}}{{if eq .Destination "/etc/caddy/Caddyfile"}}{{.Source}}{{end}}{{end}}')"
[ -n "$MOUNT" ] && [ "$(readlink -f "$MOUNT")" = "$(readlink -f "$DIA/Caddyfile")" ] || fail "Live Caddyfile mount differs: $MOUNT"
docker exec "$CADDY_ID" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null || fail 'Existing Caddy config invalid'
if grep -Fq "$DOMAIN" "$DIA/Caddyfile" && ! grep -Fq '# BEGIN FOROSH SAMANEPANEL MANAGED' "$DIA/Caddyfile"; then
  fail 'Domain already present in Caddyfile. Refusing to replace another site block.'
fi

cd "$FRESH"
[ "$(git branch --show-current)" = dia-darma-fresh ] || fail 'Unexpected Git branch'
git diff --quiet && git diff --cached --quiet || fail 'Tracked changes detected in fresh project'
echo '== Updating and testing only the independent Samanepanel deployment =='
git fetch origin dia-darma-fresh
git pull --ff-only origin dia-darma-fresh
bash deploy/darma-fresh/upgrade_sales_channels.sh

# Keep local backups outside Git and preserve .env credentials.
umask 077
mkdir -p "$FRESH/backups"
STAMP="$(date +%Y%m%d-%H%M%S)"
cp -p "$FRESH/.env" "$FRESH/backups/forosh-env-$STAMP"
cp -p "$DIA/Caddyfile" "$FRESH/backups/dia-Caddyfile-before-forosh-$STAMP"

python3 - "$FRESH/.env" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
updates = {
 'ALLOWED_HOSTS': 'forosh.filmjadiid.ir,localhost,127.0.0.1',
 'CSRF_TRUSTED_ORIGINS': 'https://forosh.filmjadiid.ir',
 'DIA_DARMA_SSH_ONLY': '0',
 'DEBUG': '0',
}
seen, lines = set(), []
for line in p.read_text().splitlines():
    key = line.split('=', 1)[0] if '=' in line else None
    if key in updates:
        if key not in seen:
            lines.append(key + '=' + updates[key])
            seen.add(key)
    else:
        lines.append(line)
for key, value in updates.items():
    if key not in seen:
        lines.append(key + '=' + value)
p.write_text('\n'.join(lines) + '\n')
p.chmod(0o600)
print('Production host, CSRF and secure cookies configured.')
PY

# Only the new web joins a dedicated bridge with the existing Caddy.
# It does NOT join Dia Gallery's app/database Docker network.
docker network inspect forosh_edge >/dev/null 2>&1 || docker network create --driver bridge forosh_edge >/dev/null
docker compose -f "$COMPOSE" config --quiet
docker compose -f "$COMPOSE" up -d --no-deps web
WEB_ID="$(docker compose -f "$COMPOSE" ps -q web)"
[ -n "$WEB_ID" ] || fail 'Fresh web container not running'
docker inspect "$WEB_ID" --format '{{json .NetworkSettings.Networks}}' | grep -Fq '"forosh_edge"' || fail 'Web not on forosh_edge'
if ! docker inspect "$CADDY_ID" --format '{{json .NetworkSettings.Networks}}' | grep -Fq '"forosh_edge"'; then
  docker network connect forosh_edge "$CADDY_ID"
fi

# Check internal upstream before changing the original Caddy configuration.
READY=0
for i in $(seq 1 30); do
  if docker exec "$CADDY_ID" wget -q -O /dev/null http://forosh-web:8000/login/ 2>/dev/null; then
    READY=1; break
  fi
  sleep 2
done
[ "$READY" -eq 1 ] || fail 'Existing Caddy cannot reach new web. Dia config NOT modified.'

if ! grep -Fq '# BEGIN FOROSH SAMANEPANEL MANAGED' "$DIA/Caddyfile"; then
  # Must append in-place: Caddy uses a read-only bind mount of this file inode.
  cat >> "$DIA/Caddyfile" <<'CADDY'

# BEGIN FOROSH SAMANEPANEL MANAGED
forosh.filmjadiid.ir {
    encode zstd gzip
    reverse_proxy forosh-web:8000
}
# END FOROSH SAMANEPANEL MANAGED
CADDY
else
  grep -Fq 'reverse_proxy forosh-web:8000' "$DIA/Caddyfile" || fail 'Managed Caddy block changed; inspect manually'
fi

restore_caddy() {
  echo 'Caddy failed validation/reload. Restoring previous configuration.' >&2
  cat "$FRESH/backups/dia-Caddyfile-before-forosh-$STAMP" > "$DIA/Caddyfile"
  docker exec "$CADDY_ID" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile || true
}
if ! docker exec "$CADDY_ID" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  restore_caddy
  fail 'New domain config invalid; old config restored'
fi
if ! docker exec "$CADDY_ID" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile; then
  restore_caddy
  fail 'Caddy reload failed; old config restored'
fi

# Certificate issuance can be pending until the public DNS record is configured.
echo '== Checking HTTPS certificate and route =='
HTTPS_OK=0
for i in $(seq 1 12); do
  STATUS="$(curl --noproxy '*' --silent --max-time 8 --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null -w '%{http_code}' "https://$DOMAIN/login/" 2>/dev/null || true)"
  if [ "$STATUS" = 200 ]; then HTTPS_OK=1; break; fi
  sleep 3
done
echo 'DIA_CADDY_CONFIG_RELOADED_OK'
if [ "$HTTPS_OK" -eq 1 ]; then
  echo "FOROSH_HTTPS_READY=https://$DOMAIN/login/"
else
  echo 'DOMAIN_CONFIG_READY_BUT_HTTPS_NOT_VERIFIED'
  echo 'Check DNS A record, open TCP 80/443 and Caddy TLS issuance.'
  echo 'With Cloudflare proxy, set SSL/TLS to Full (strict) once origin TLS is valid.'
fi
printf 'DNS IPv4: '
getent ahostsv4 "$DOMAIN" 2>/dev/null | awk '{print $1}' | sort -u | paste -sd ',' - || true
echo "Caddyfile backup: $FRESH/backups/dia-Caddyfile-before-forosh-$STAMP"
docker compose -f "$COMPOSE" ps
