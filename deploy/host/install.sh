#!/usr/bin/env bash
# Install/update the host side of the QuickBooks MCP deployment per source ≠ deployment.
# Run with sudo from the repo. Does NOT touch /var/lib/quickbooks-mcp (live tokens) or
# /etc/quickbooks-mcp/keys. Image builds and `docker compose up -d` stay manual (README).
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"

install -d -o root -g root -m 755 /srv/apps/quickbooks-mcp /srv/apps/quickbooks-mcp/bin
install -m 644 -o root -g root "$SRC/compose.yaml" /srv/apps/quickbooks-mcp/compose.yaml
install -m 644 -o root -g root "$SRC/README.md"    /srv/apps/quickbooks-mcp/README.md
install -m 755 -o root -g root "$SRC/bin/keepalive.py" /srv/apps/quickbooks-mcp/bin/keepalive.py

install -d -o root -g root -m 755 /etc/quickbooks-mcp
install -m 644 -o root -g root "$SRC/keepalive.json" /etc/quickbooks-mcp/keepalive.json
# keepalive.env (SLACK_WEBHOOK_URL) is provisioned by hand, root:root 0600; never in git.

install -m 644 "$SRC/qbo-mcp-keepalive.service" /etc/systemd/system/
install -m 644 "$SRC/qbo-mcp-keepalive.timer"   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now qbo-mcp-keepalive.timer
systemctl list-timers 'qbo-mcp-*' --no-pager
