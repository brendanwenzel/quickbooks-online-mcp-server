# Remote deployment

`Dockerfile.remote` runs the MCP stdio server behind Supergateway:

- MCP SSE traffic and `/healthz` listen on port `8080`.
- The one-time Intuit OAuth callback listener starts on port `8000` only while
  authorization is in progress.
- `/data/.env` is persistent token storage; the image links it to `/app/.env`.
  The container runs as the unprivileged UID/GID `1999`.

## Required configuration

Provide these values through the deployment platform's secret manager (never
commit them or bake them into the image):

```text
QUICKBOOKS_CLIENT_ID
QUICKBOOKS_CLIENT_SECRET
QUICKBOOKS_ENVIRONMENT=production
QUICKBOOKS_REDIRECT_URI=https://<public-oauth-host>/callback
QUICKBOOKS_TOKEN_ENCRYPTION_KEY_FILE=/run/secrets/qbo-token-encryption.key
```

Mount a persistent writable volume at `/data` and a read-only file containing
exactly 32 random bytes (hex or base64 encoded) at the configured key path.
The key file must be readable by UID `1999`. With the key configured, refresh
tokens and realm IDs are stored in `/data/.env` only as authenticated,
encrypted values.

## Public routing and first authorization

Route MCP clients to port `8080`. Intuit must be able to reach the exact
`QUICKBOOKS_REDIRECT_URI`; route its `/callback` path to port `8000` while the
OAuth flow is active. The redirect URI registered in the Intuit developer
portal must match exactly, including the scheme, host, port, and path.

If the hosting platform exposes only one public port and cannot route
`/callback` to port `8000`, this image's built-in callback listener cannot
complete production OAuth. Configure a second public listener/reverse-proxy
route first, or perform the one-time OAuth flow in an approved environment
that can receive the callback and securely provision the encrypted resulting
values to `/data/.env`.

In a headless container, initiate authorization with an MCP request that needs
authentication, then open the authorization URL emitted in the service logs in
your own browser. Do not log, paste, or share the resulting code/token values.

## Local image smoke check

```bash
docker build -f Dockerfile.remote -t qbo-mcp-remote:local .
docker run --rm --entrypoint supergateway qbo-mcp-remote:local --help
```

The normal container command starts Supergateway with
`node dist/index.js`, port `8080`, and `/healthz`; it requires the production
configuration above before it can serve authenticated QuickBooks requests.
