# Reverse Proxy Configuration

When deploying behind a reverse proxy (nginx, Caddy, etc.), you must increase
timeout settings so that batch annotation requests are not killed prematurely.

## Recommended nginx settings

```nginx
location /api/ {
    proxy_pass http://backend:8001/api/;

    # Timeouts — batch annotation can take several minutes
    proxy_read_timeout  300s;
    proxy_send_timeout  300s;
    proxy_connect_timeout 10s;

    # Required for SSE streaming (used by /api/annotate/batch/stream)
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    chunked_transfer_encoding off;

    # Standard proxy headers
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

### Key directives

| Directive | Purpose |
|-----------|---------|
| `proxy_read_timeout 300s` | Prevents 504 errors during long batch jobs |
| `proxy_buffering off` | Required for SSE — ensures events reach the client immediately |
| `proxy_cache off` | Prevents caching of streaming responses |

## How the application handles proxies

The batch annotation endpoint (`/api/annotate/batch/stream`) uses **Server-Sent
Events (SSE)** to stream progress updates as each prompt completes. This keeps
data flowing on the connection, which prevents proxy idle timeouts even with
conservative `proxy_read_timeout` settings.

If SSE streaming fails (e.g., the proxy does not support it), the frontend
automatically falls back to the standard `/api/annotate/batch` endpoint.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VLLM_CONCURRENCY` | `8` | Max parallel vLLM calls per batch request |
| `VLLM_TIMEOUT` | `150` | Per-request timeout (seconds) for vLLM API calls |
| `CORS_ORIGINS` | — | Additional allowed origins (comma-separated) |
