# Host Caddy deployment discovered on 2026-10-31

Live server diagnostics show **Caddy is a host process** listening on TCP
80/443 (not a Docker container). The Dia Gallery Django web container is
published on host loopback 8001; the new standalone Samanepanel web is
published on loopback 18081.

**Use deploy/darma-fresh/enable_forosh_host_caddy.sh instead of
enable_forosh_domain.sh.** The old script is intended for a Docker Caddy
installation and will deliberately refuse to run against this server.

Download from the **Git branch** to avoid stale raw.githubusercontent.com
responses:

```bash
cd /opt/dia-darma-fresh
git fetch origin dia-darma-fresh
git show FETCH_HEAD:deploy/darma-fresh/enable_forosh_host_caddy.sh > /root/enable_forosh_host_caddy.sh
grep -q HOST_CADDY_CONFIG_LOADED /root/enable_forosh_host_caddy.sh && bash /root/enable_forosh_host_caddy.sh
```

The new script identifies the ACTIVE Caddy configuration from the running
host Caddy process command line. It validates the existing Caddyfile,
confirms it serves samaneh.filmjadiid.ir, backs up the Caddyfile and
the isolated Samanepanel .env, adjusts only the Samanepanel host/HTTPS
settings and web container, then appends a separate domain block targeting
127.0.0.1:18081 and reloads host Caddy without restarting it. On config
validation or reload failure it restores the original Caddyfile.

If its active Caddy configuration cannot be proven, it stops before any
modification. The installer does not automatically change DNS. A DNS
A record `forosh` should point to the correct public server address.

---

# Serve independent Samanepanel on https://forosh.filmjadiid.ir

The Dia Gallery repository documents a Caddy-based deployment, but the live server may use a different checkout path. The installer discovers the **actual running Caddyfile host bind mount** via `docker inspect` and checks the existing `samaneh.filmjadiid.ir` site block; it never assumes `/opt/dia-gallery/Caddyfile` exists. If no unambiguous match exists, it prints running containers/listening ports and stops without modifying the reverse proxy.
The new project uses `/opt/dia-darma-fresh` and Compose project
`dia-darma-fresh`. Do not start a second Caddy on 80/443.

This installer:
1. Searches running Docker containers for exactly one live Caddyfile bind mount containing `samaneh.filmjadiid.ir`, confirms the Caddy config is valid, and refuses to modify a different site's config.
2. Updates only `dia-darma-fresh` via the tested upgrade workflow, preserving its PostgreSQL and DigiKala SQLite volumes.
3. Backs up both the fresh project's `.env` and original Dia Gallery Caddyfile to `/opt/dia-darma-fresh/backups`.
4. Configures `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, and secure session/CSRF cookies on HTTPS.
5. Creates network `forosh_edge`, to which only the **fresh web** container and **existing Caddy** connect. It does not join the fresh Django web to Dia Gallery's internal PostgreSQL network.
6. Confirms Caddy can reach the Django login endpoint before editing the live Caddyfile.
7. Appends only a standalone `forosh.filmjadiid.ir` site block **in-place**, preserving the bind-mount inode.
8. Validates Caddy, reloads it without recreating or stopping Dia Gallery, and restores the backed-up Caddyfile if validation/reload fails.
9. Checks origin HTTPS. If DNS has not propagated, Caddy can await ACME issuance; the script prints that HTTPS has not been verified.

## DNS record
Create an `A` record in the DNS provider for subdomain `forosh` pointing
at the **actual public IP of this Dia Gallery server**. Previously the
server was accessed at `5.202.75.90`; confirm this is still the current
address before saving the record. Avoid conflicting A/AAAA records.

If Cloudflare is used, initially DNS-only (grey-cloud) simplifies ACME TLS
verification; after origin HTTPS is valid, proxied mode with Full (strict)
may be enabled. TCP 80/443 must be reachable from the internet.

## Run on Dia server as root
```bash
curl -fsSL https://raw.githubusercontent.com/aliiitavazoeiii-afk/samanepanel/dia-darma-fresh/deploy/darma-fresh/enable_forosh_domain.sh -o /root/enable_forosh_domain.sh
bash /root/enable_forosh_domain.sh
```

Visit `https://forosh.filmjadiid.ir/login/` once the script reports
`FOROSH_HTTPS_READY` and DNS points correctly. If only
`DOMAIN_CONFIG_READY_BUT_HTTPS_NOT_VERIFIED` appears, do not treat HTTPS
as live. Inspect:
```bash
docker logs --tail=100 "$(docker ps -q --filter label=com.docker.compose.project=dia-gallery --filter label=com.docker.compose.service=caddy)"
getent ahostsv4 forosh.filmjadiid.ir
```

Caddy's live Caddyfile may be outside the directory indicated in Dia's deployment documentation; it is identified from the running container and will receive a local modification on its host. A future `git checkout`, `git reset`, or
Caddy container **recreation** can remove this route or its manually attached
edge network. Do not use destructive Git resets. If Dia Caddy is recreated,
rerun this installer to reattach and reload. Ordinary container restarts
retain their network memberships.

The original Dia Gallery production Django app and database are never edited
by this installer. This does not itself set external DNS records.
