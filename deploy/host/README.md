# QuickBooks Online MCP deployment

This deployment runs three isolated copies of Intuit's QuickBooks Online MCP
server. Each has a separate persistent `.env`, OAuth refresh token, realm ID,
HTTP/SSE endpoint, and bearer token.

## Source of truth

This directory (`deploy/host/` in the fork) is the checked-in copy of the host-side
deploy tree. `sudo deploy/host/install.sh` installs compose.yaml, this README, the
keep-alive watchdog and its systemd units. Live tokens and encryption keys are never
touched by the installer.

## Runtime locations

- Source: `/home/coral/src/quickbooks-online-mcp-server`
- Deployment: `/srv/apps/quickbooks-mcp` (from `deploy/host/` in the source repo)
- Account credentials: `/var/lib/quickbooks-mcp/<account-slug>/.env`
- Per-account encryption keys: `/etc/quickbooks-mcp/keys/<account-slug>.key`
- Client endpoint secrets: `/home/coral/.config/quickbooks-mcp/endpoints.env`
- Caddy route: `/etc/caddy/qbo-mcp.caddy`

OAuth refresh credentials and realm IDs are stored with AES-256-GCM encryption;
the encryption keys are mounted read-only from a separate root-owned directory.
Gateway payload logging is disabled.

## Public legal pages

- EULA: `https://mcp.brendanwenzel.org/legal/eula/`
- Privacy policy: `https://mcp.brendanwenzel.org/legal/privacy/`

## Intuit setup

Create one production QuickBooks Online app and register all three redirect URIs:

- `https://mcp.brendanwenzel.org/oauth/cute-n-country/callback`
- `https://mcp.brendanwenzel.org/oauth/surfers-of-light/callback`
- `https://mcp.brendanwenzel.org/oauth/salty-ecom/callback`

Put the production Client ID and Client Secret into all three account `.env`
files, then restart the containers.

The three endpoint display names are:

- Cute n Country Quickbooks
- Surfers of Light Quickbooks
- Salty Ecom Quickbooks

## Authorize an account

Run the command below, open the authorization URL printed in the log, sign in,
and select the intended QBO company. Repeat for each service.

```bash
cd /srv/apps/quickbooks-mcp
sudo docker compose exec cute-n-country npm run auth
sudo docker compose restart cute-n-country
```

## Keep-alive watchdog

`qbo-mcp-keepalive.timer` runs `/srv/apps/quickbooks-mcp/bin/keepalive.py` daily at
06:30 UTC. For each company it calls `get_company_info` on the container's local port
(forcing a token refresh whenever the access token has expired, which rotates the
Intuit refresh token and keeps the 100-day inactivity clock reset), checks the
company name against `/etc/quickbooks-mcp/keepalive.json`, and checks that the public
route still returns 401 without a bearer. Any failure posts to Slack `#finance`
(`SLACK_WEBHOOK_URL` in `/etc/quickbooks-mcp/keepalive.env`, root-only) and fails the
unit so `error-notify@` fires too. A weekly heartbeat posts on Mondays.

```bash
sudo systemctl start qbo-mcp-keepalive.service      # run now
journalctl -u qbo-mcp-keepalive.service -n 30       # last report
sudo QBO_KEEPALIVE_HEARTBEAT=1 systemctl start ...  # (edit the unit env to force a post)
```

## Re-authorize a company

If the watchdog reports a dead token: remove the two `*_ENCRYPTED` lines from that
company's `.env` (back it up first), `sudo docker compose restart <svc>`, then run
the authorize command above and open the printed URL. Do not `timeout` the exec; it
leaves node holding port 8000 (restart the container to clear).

## Operations

```bash
cd /srv/apps/quickbooks-mcp
sudo docker compose ps
sudo docker compose logs --tail=100 cute-n-country
sudo docker compose up -d
```

Rebuild the image from the repo root and point compose at the new tag:

```bash
SHA=$(git rev-parse --short=12 HEAD)
sudo docker build -f Dockerfile.remote --label org.opencontainers.image.revision=$SHA \
  -t local/quickbooks-online-mcp-server:$SHA .
# edit the image: line in deploy/host/compose.yaml, then:
sudo deploy/host/install.sh && cd /srv/apps/quickbooks-mcp && sudo docker compose up -d
~/src/catalog/bin/reconcile.sh
```

Write policy (Brendan, 2026-09-09): `QUICKBOOKS_DISABLE_WRITE=false`,
`QUICKBOOKS_DISABLE_UPDATE=false`, `QUICKBOOKS_DISABLE_DELETE=true` in every
account `.env` — create and update for bookkeeping, never delete (finance SPEC).
Change a flag, then restart only that account's container.
