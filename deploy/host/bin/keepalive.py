#!/usr/bin/env python3
"""QuickBooks MCP keep-alive and token watchdog.

Runs daily from qbo-mcp-keepalive.timer. For every company endpoint it opens an
MCP session against the container's local port, calls get_company_info, and
checks the company name. The call forces a token refresh whenever the access
token has expired, which rotates and persists the Intuit refresh token — so the
100-day inactivity expiry can never sneak up on a quiet company. It also checks
that the public Caddy route still gates the endpoint (401 without a bearer).

Failures post to Slack (SLACK_WEBHOOK_URL, the #finance webhook) and exit 1 so
OnFailure=error-notify@ fires as well. Success is silent except for a weekly
heartbeat on HEARTBEAT_WEEKDAY (0 = Monday), or always with QBO_KEEPALIVE_HEARTBEAT=1.

Config: /etc/quickbooks-mcp/keepalive.json
  {"public_host": "mcp.brendanwenzel.org", "heartbeat_weekday": 0,
   "targets": [{"slug": "salty-ecom", "port": 18003, "expect": "SALTY ECOM, INC."}, ...]}
No secrets are read other than the webhook; no financial data is fetched or logged.
"""
from __future__ import annotations

import datetime as dt
import http.client
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

CONFIG_PATH = os.environ.get("QBO_KEEPALIVE_CONFIG", "/etc/quickbooks-mcp/keepalive.json")
CALL_TIMEOUT = float(os.environ.get("QBO_KEEPALIVE_TIMEOUT", "60"))


class SseSession:
    """Minimal MCP-over-SSE client: one GET stream plus JSON-RPC POSTs."""

    def __init__(self, host: str, port: int, strip_prefix: str = ""):
        self.host, self.port = host, port
        # The gateway advertises its message path under the public base URL
        # (/<slug>/message). Caddy strips /<slug> before proxying; talking to the
        # container directly, we must strip it ourselves.
        self.strip_prefix = strip_prefix
        self.endpoint: str | None = None
        self.messages: dict[int, dict] = {}
        self._ready = threading.Event()
        self._conn = http.client.HTTPConnection(host, port, timeout=CALL_TIMEOUT)
        self._conn.request("GET", "/sse", headers={"Accept": "text/event-stream"})
        self._resp = self._conn.getresponse()
        if self._resp.status != 200:
            raise RuntimeError(f"GET /sse -> HTTP {self._resp.status}")
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()
        if not self._ready.wait(CALL_TIMEOUT):
            raise RuntimeError("no endpoint event from /sse")

    def _pump(self) -> None:
        event = None
        try:
            for raw in self._resp:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event == "endpoint" or (self.endpoint is None and data.startswith("/")):
                        path = data if data.startswith("/") else "/" + data.split("://", 1)[-1].split("/", 1)[-1]
                        if self.strip_prefix and path.startswith(self.strip_prefix + "/"):
                            path = path[len(self.strip_prefix):]
                        self.endpoint = path
                        self._ready.set()
                    else:
                        try:
                            msg = json.loads(data)
                        except ValueError:
                            continue
                        if isinstance(msg, dict) and isinstance(msg.get("id"), int):
                            self.messages[msg["id"]] = msg
                elif line == "":
                    event = None
        except Exception:  # stream closed; callers time out on wait()
            pass

    def post(self, payload: dict) -> None:
        assert self.endpoint
        conn = http.client.HTTPConnection(self.host, self.port, timeout=CALL_TIMEOUT)
        conn.request("POST", self.endpoint, body=json.dumps(payload),
                     headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        resp.read()
        conn.close()
        if resp.status not in (200, 202):
            raise RuntimeError(f"POST {self.endpoint.split('?')[0]} -> HTTP {resp.status}")

    def wait(self, msg_id: int, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msg_id in self.messages:
                return self.messages[msg_id]
            time.sleep(0.2)
        raise TimeoutError(f"no response to request {msg_id} within {timeout:.0f}s")

    def close(self) -> None:
        # The pump thread is blocked in a read on the stream; shut the socket
        # down so it unblocks immediately instead of waiting out the timeout.
        for action in (lambda: self._conn.sock.shutdown(socket.SHUT_RDWR),
                       self._resp.close, self._conn.close):
            try:
                action()
            except Exception:
                pass


def check_company(target: dict) -> tuple[bool, str]:
    slug, port, expect = target["slug"], int(target["port"]), target["expect"]
    started = time.monotonic()
    verbose = os.environ.get("QBO_KEEPALIVE_VERBOSE") == "1"

    def mark(step: str) -> None:
        if verbose:
            print(f"  [{slug}] {step} at +{time.monotonic() - started:.1f}s", file=sys.stderr)
    try:
        s = SseSession("127.0.0.1", port, strip_prefix=f"/{slug}")
        mark("sse endpoint")
        try:
            s.post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "qbo-mcp-keepalive", "version": "1"}}})
            s.wait(1, CALL_TIMEOUT)
            mark("initialized")
            s.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
            s.post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "get_company_info", "arguments": {"params": {}}}})
            reply = s.wait(2, CALL_TIMEOUT)
            mark("company info")
            elapsed = time.monotonic() - started
        finally:
            s.close()
            mark("closed")
    except (OSError, RuntimeError, TimeoutError, socket.timeout) as exc:
        return False, f"{slug}: transport failure: {exc}"
    result = reply.get("result") or {}
    text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
    if "error" in reply or result.get("isError"):
        detail = text or json.dumps(reply.get("error"))
        return False, f"{slug}: tool error: {detail[:300]}"
    try:
        name = json.loads(text).get("CompanyName")
    except (ValueError, AttributeError):
        return False, f"{slug}: unparseable company info"
    if name != expect:
        return False, f"{slug}: WRONG COMPANY: got {name!r}, expected {expect!r}"
    return True, f"{slug}: ok ({name}, {elapsed:.1f}s)"


def check_gate(public_host: str, slug: str) -> tuple[bool, str]:
    url = f"https://{public_host}/{slug}/healthz"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return False, f"{slug}: public route answered {r.status} WITHOUT a bearer (gate down?)"
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return True, f"{slug}: public route gated (401)"
        return False, f"{slug}: public route HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        return False, f"{slug}: public route unreachable: {e}"


def slack(text: str) -> None:
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        print("(no SLACK_WEBHOOK_URL; not posting)", file=sys.stderr)
        return
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode(errors="replace").strip()
    if body != "ok":
        raise RuntimeError(f"slack returned {r.status}: {body[:200]}")


def main() -> int:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        cfg = json.load(fh)
    lines, ok = [], True
    for target in cfg["targets"]:
        good, msg = check_company(target)
        ok &= good
        lines.append(("✅ " if good else "❌ ") + msg)
        if cfg.get("public_host"):
            good, msg = check_gate(cfg["public_host"], target["slug"])
            ok &= good
            lines.append(("✅ " if good else "❌ ") + msg)
    report = "\n".join(lines)
    print(report)
    today = dt.date.today()
    heartbeat = os.environ.get("QBO_KEEPALIVE_HEARTBEAT") == "1" or \
        today.weekday() == int(cfg.get("heartbeat_weekday", 0))
    if not ok:
        slack(f"*QuickBooks MCP keep-alive FAILED* ({today.isoformat()})\n{report}\n"
              "Re-authorize: see Systems registry entry “QuickBooks Online MCP”.")
        return 1
    if heartbeat:
        slack(f"QuickBooks MCP keep-alive: all companies OK ({today.isoformat()})\n{report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
