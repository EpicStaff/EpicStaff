# Serve public paths

Requests to a plugin's backend reach it through EpicStaff's gateway at
`https://<id>.<plugins base domain>/api/**`. A path you declare **public** is forwarded without an
EpicStaff login: a health probe, a webhook a third party calls, a page anyone may fetch. Every
other path needs a person logged in to the plugin through EpicStaff, whose plugin login token the
gateway checks ([Gateway context](../reference/gateway-context.md#who-is-asking-user-contexts));
without one it is answered `401 login_required`.

## Declare them

```json
"public_paths": [
  { "path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0 },
  { "path": "/api/hooks/github", "match": "exact", "methods": ["POST"], "rate_limit_per_minute": 120, "max_body_kb": 512 }
]
```

| Field | Meaning |
|---|---|
| `path` | Under `/api/`, without `.` or `..` segments |
| `match` | `exact`: only this path. `prefix`: this path and everything below it, by whole segments, so `/api/public` covers `/api/public/feed` but not `/api/publicity`. A prefix ending in `/` covers only what is below it |
| `methods` | The methods that may use it: any of `GET HEAD POST PUT PATCH DELETE OPTIONS`. `HEAD` is not implied by `GET` |
| `rate_limit_per_minute` | 1–6000, and at most the deployment's `PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE` |
| `max_body_kb` | 0–20480, and at most the deployment's `PLUGINS_MAX_REQUEST_BODY_MB` × 1024; `0` allows no body |

The first rule whose method and path match is used. A package that asks for more than the
deployment allows is refused at upload (`invalid_plugin`, located at
`manifest.public_paths[<i>].rate_limit_per_minute` or `.max_body_kb`).

## What the gateway checks, in order

1. **The plugin is installed with a backend and in service**, otherwise `404 not_found`: also
   while it is uninstalled or being deleted.
2. **The path is canonical**, otherwise `404 not_found`. A request is matched on its path only
   as the client sent it, decoded once; it is refused if that differs from the normalised path
   (doubled slashes, `.` or `..` segments, `%2e%2e`), if it holds control characters or is not
   UTF-8, or if decoding it a second time gives a dot segment or a path into the platform's
   `/_epicstaff/` paths. So a request can never be checked as one path and reach your backend
   as another.
3. **The plugin is up.** While it is stopped for an upgrade every path, public ones included, is
   answered `503 plugin_maintenance`; while its process is not running and healthy,
   `503 plugin_unavailable`.
4. **The method and path match a public path.** Otherwise the request needs a plugin login token
   and a person who may use the plugin ([who is
   asking](../reference/gateway-context.md#who-is-asking-user-contexts)), and the two checks
   below do not apply.
5. **The body fits** `max_body_kb`, judged by the request's `Content-Length`. A body without a
   declared length is refused, because its size is not known until it has streamed: a chunked
   request, and any `POST`, `PUT`, `PATCH` or `DELETE` without `Content-Length` (over HTTP/2 a
   body needs no length). Otherwise `413 request_too_large`. Clients of a public path should
   always send `Content-Length`, `Content-Length: 0` for an empty body.
6. **The client is within the rate limit**, otherwise `429 rate_limited` with `Retry-After: 60`.
   Requests are counted per public path and per client address, in fixed one-minute windows
   that start on the minute, so a client can get up to twice the limit across a window boundary.

The query string plays no part in the match.

## What your backend receives

- The request as the client sent it, with a gateway context in `X-EpicStaff-Plugin-Context` whose
  `mode` is `public`: no user, no organization, no permissions, and the request's method and
  path. The Python SDK verifies it before your code runs. See [Gateway context](../reference/gateway-context.md).
- The client's `Authorization` header, **only on public paths**: a token your plugin issued (an
  MCP or webhook bearer token, say) is yours to check. On every other path it is removed.
- Never the browser's cookies. Plugins use tokens, not cookies.

And what the client receives from your response: everything except `Set-Cookie` (a plugin cannot
set cookies on the plugins domain) and `X-Accel-Redirect`, which are dropped.

## Check it

```
curl -i https://weather.plugins.example.com/api/ping
```

answers with your backend's response. A path that is not public answers
`401 {"status_code":401,"code":"login_required",…}` to a request without a plugin login token,
without reaching the backend.
