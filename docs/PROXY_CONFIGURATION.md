# Reverse Proxy Configuration

When deploying behind a reverse proxy (nginx, Caddy, etc.), there are two
things to get right:

1. The proxy must be configured to handle the SSE batch-progress stream
   without buffering, with timeouts long enough to cover real batch
   durations.
2. `NEXT_PUBLIC_API_URL` must be set so the browser actually routes API
   requests through the proxy rather than hitting the backend directly.

Get either wrong and you will see symptoms like a "frozen UI", `Offline`
status indicator, or empty prompt lists even when the backend is healthy.

## NEXT_PUBLIC_API_URL: pick the right value for your topology

`NEXT_PUBLIC_API_URL` is baked into the Next.js bundle at build time and
evaluated by the browser. It must point to a URL the browser can reach.

| Deployment | Value |
|---|---|
| With reverse proxy routing `/api/*` to the backend | `/api` |
| No reverse proxy, browser on the same host as the backend | `http://localhost:8001` |
| No reverse proxy, browser on a different host | `http://<host-ip-or-domain>:8001` |

### How the value gets into the bundle

This variable is passed to the frontend Dockerfile as a **build arg** (see
the `annotation-web` service in `docker-compose.yml`):

```yaml
annotation-web:
  build:
    args:
      NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://localhost:8001}
```

Setting it under `environment:` instead of `build.args:` has **no effect**
on the browser-side URL, because Next.js inlines `NEXT_PUBLIC_*` constants
at build time, not runtime. If you only set it as a runtime env var, the
bundle keeps whatever value was baked in at the last build.

### Rebuilding without cache

After changing this value, rebuild the frontend container **without
Docker's layer cache** so the build arg actually triggers a rebuild of the
Next.js bundle:

```bash
docker compose build --no-cache annotation-web
docker compose up -d
```

A plain `docker compose build` may reuse cached layers and ship the old
URL even though the build arg changed.

### Verifying

Open DevTools in the browser, Network tab, and trigger any action that
calls the backend (e.g. open the Dashboard). Confirm API requests go to
the URL you expect:

- Reverse-proxy deployment: requests should be relative (`/api/...`) and
  share the page origin.
- Direct deployment: requests should go to `http://<host>:8001/api/...`.

### Common mistake

Setting `NEXT_PUBLIC_API_URL=http://localhost:8001` while a reverse proxy
is in front. With this value the browser bypasses the proxy, which means
none of the proxy's timeout/buffering settings apply, and (if the browser
is remote) the request just fails because `localhost` resolves to the
client machine, not the server. Symptom: page loads fine, dashboard shows
`Offline`, prompt list is empty, no `/api/*` requests visible in the
reverse-proxy access log.

## Recommended nginx config

Two location blocks are needed. The streaming endpoint must come first
(more specific prefix wins) and disable buffering.

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 50M;

    # SSE streaming endpoint for batch annotation progress.
    # Buffering is disabled so progress events reach the browser
    # immediately instead of being collected by nginx until the buffer
    # fills. MUST come before the generic /api/ block.
    location ^~ /api/annotate/batch/stream {
        proxy_pass http://annotation-api:8001/annotate/batch/stream;

        # Critical for Server-Sent Events
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
        add_header X-Accel-Buffering no always;

        # Allow long-running batches (up to 24h)
        proxy_connect_timeout 60s;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Generic API routes
    location /api/ {
        proxy_pass http://annotation-api:8001/;

        proxy_connect_timeout 60s;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Frontend
    location / {
        proxy_pass http://annotation-web:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Key directives

| Directive | Purpose |
|---|---|
| `proxy_buffering off` | Required for SSE. Without this nginx collects events into ~1MB chunks before forwarding, and the UI looks frozen even when the backend is working |
| `add_header X-Accel-Buffering no` | Same intent for clients (and downstream proxies) that respect this hint |
| `proxy_http_version 1.1` + `Connection ""` | Required for SSE to keep the connection alive |
| `proxy_read_timeout 86400s` | Long batches can run for hours. The default (60s) and `300s` are both too short |
| `chunked_transfer_encoding off` | Avoids extra framing on top of SSE event boundaries |

### Reload after edits

```bash
docker compose exec reverse-proxy nginx -t       # validate
docker compose restart reverse-proxy             # apply
```

## How the application uses the proxy

The batch annotation endpoint (`/api/annotate/batch/stream`) uses
**Server-Sent Events (SSE)** to stream a `done with note N` event after
each prompt completes. The frontend reads these events to drive the
progress bar and to update the per-note status in real time.

If SSE streaming fails (proxy doesn't support it, or the client is offline
behind the proxy), the frontend falls back to the standard
`/api/annotate/batch` endpoint which returns once the batch is complete.

A separate background-job mode (planned) will allow long batches to
outlive a client disconnect entirely; in that mode the proxy timeout
matters less because the heavy work is decoupled from the connection.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Dashboard says `LLM Server Status: Offline` even though `curl /api/server/status` returns `available` | `NEXT_PUBLIC_API_URL` points somewhere the browser can't reach. See the table above |
| UI looks frozen during a batch but backend logs show progress | nginx is buffering the SSE stream. Add the dedicated streaming `location` block with `proxy_buffering off` |
| 504 Gateway Timeout during long batches | `proxy_read_timeout` too low. Bump to `86400s` |
| App "stops processing" after VPN drops, GPU goes idle, no logs | Backend SSE generator is wedged on a write to a closed socket. Disable `proxy_buffering` so nginx closes the upstream cleanly when the client disconnects |
| Empty Center/Group dropdown in the prompt editor | Same as the first row: the frontend can't reach `/api/prompts`, check `NEXT_PUBLIC_API_URL` |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `VLLM_CONCURRENCY` | `8` | Max parallel vLLM calls per batch request |
| `VLLM_TIMEOUT` | `150` | Per-request timeout (seconds) for vLLM API calls |
| `CORS_ORIGINS` | — | Additional allowed origins (comma-separated) |
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001` | URL the browser uses to reach the backend (see table above) |
