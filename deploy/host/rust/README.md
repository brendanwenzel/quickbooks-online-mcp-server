# QBO watchdog Rust candidate

Source-only port of the maintained host watchdog. The upstream Intuit MCP server,
containers, OAuth data and their configuration are outside this change. The
installed Python watchdog remains active. No real QBO or Slack request was made
while implementing or verifying this candidate.

Baseline `deploy/host/bin/keepalive.py` and the installed watchdog have identical
SHA-256 `c3d00adfba5b2311c5dd39ed608c19cd31dff7c8be06a12325fb556d4bc6dc46`.
Finance SPEC section 8 still applies. The only MCP tool invoked is
`get_company_info`; no ledger records, vendors or transactions are fetched or
changed by this code. Its normal company-info call retains the upstream server's
existing OAuth refresh behavior.

The wire sequence remains GET `/sse`, initialize protocol `2024-11-05`, wait for
ID 1, send `notifications/initialized`, call `get_company_info` with empty params,
then wait for ID 2 and compare CompanyName exactly. Endpoint paths retain the
configured local container origin and strip only the matching slug prefix.
Local requests bypass ambient proxy variables, as Python http.client did, and
never follow redirects. A bounded asynchronous message channel replaces the
200 ms polling loop; local JSON-RPC POSTs share one pooled connection. Companies
and their public-gate checks remain sequential and in configuration order.

Public gate checks retain HTTPS and certificate/hostname verification, send no
bearer, and require 401. Existing configuration/environment names, local-date
heartbeat selection, report ordering, failure exit and Slack notification policy
are retained. Success still prints the journal report but sends no Slack message
unless heartbeat is enabled. Failure always attempts the existing notification.
No missing-webhook secret is requested or substituted. No automatic application
retry, new credential or provider authority is introduced.

## Verification

```
cargo clippy --offline --manifest-path deploy/host/rust/Cargo.toml --all-targets -- -D warnings
python3 deploy/host/rust/tests/parity.py
QBO_TEST_RELEASE=1 python3 deploy/host/rust/tests/parity.py
```

The test executes the hash-pinned Python source against local fake SSE/HTTP/TLS
servers and compares the Rust implementation against it. Requests are recorded,
including the exact handshake/tool payloads and POST connection reuse. TLS tests
use a freshly generated disposable localhost certificate; production trust is not
relaxed. POST 301/302/303 redirects become GET; POST 307/308 is refused without
resending the payload, matching urllib. Missing-location 3xx statuses are failures.
Unicode diagnostics use pinned Unicode 16 categories and Python-compatible
control/nonprintable escaping. The test-only driver accepts fixture paths and a test CA. The installed
binary has no transport-injection flags or test CA option.

The 69-case release suite passed. Cases cover relative/absolute/implicit endpoints, initialization errors,
transport status failures, missing replies, wrong companies, malformed company
JSON, tool/RPC errors, six public-gate status codes, untrusted/wrong-host TLS,
Slack response bodies and full CLI silent/forced/weekly/failure notifications.
Only synthetic company names, webhook bodies and temporary config files are used.

## Explicit differences

Transport diagnostics are static and omit endpoint URLs, query strings and
webhook addresses. Timeout or connection failures therefore have different detail
wording from Python's exception strings. Protocol status failures keep their
existing wording and strip the endpoint query. A closed SSE stream is noticed
immediately rather than polling until its deadline; it remains a failed check.

SSE buffering is bounded to 1 MiB and eight queued events. Only response IDs 1
and 2 are retained because those are the only requests this watchdog sends.
Malformed non-string tool text fails closed instead of being ignored or causing
an uncaught type exception. Invalid configuration/timeouts fail with sanitized
errors; finite positive timeouts up to one day are supported. No healthy result
is substituted after malformed input or provider failure.

This port grows maintained implementation size from 213 Python lines to about
600 formatted Rust lines. No code-size reduction is claimed. The latency fixture
introduces 25 ms per SSE response to make polling observable; its timing is not a
measurement of Intuit network latency or token refresh duration. Three successful
fixture variants measured median 728.9 ms with Python and 51.9 ms with the release
Rust implementation, including stream closure. All three Rust runs reused one
POST connection; Python opened three. Timing is supplementary to the request and
response contract assertions.

## Release and rollback plan, not activated

After independent review, build the locked release binary from main and package
it with the source revision, native build target, baseline hash and checksums.
The reviewed installer must preserve the current DynamicUser identity, timer,
environment file and notification policy. Keep the Python file and exact prior
unit as the rollback target. Install only the watchdog binary and an ExecStart
binding under `/srv/apps/quickbooks-mcp`; do not rebuild or restart containers.

Activation must verify the service is idle and retain a reversible previous
binding. Do not manually invoke the installed watchdog during source verification:
that would contact real QBO endpoints and could notify Slack. Parent owns the
release decision and its separately authorized runtime verification. Rollback
restores the previous ExecStart and reloads systemd without changing company
configuration, OAuth tokens, notification credentials or the timer schedule.
