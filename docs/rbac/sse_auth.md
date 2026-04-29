# SSE Authentication — Frontend Migration Guide

**Audience:** frontend developers.
**Scope:** all `text/event-stream` (SSE) endpoints — `run-session` live stream, filtered external stream, and any future SSE route.
**Status:** required from the moment Story 2 ships. There is **no backwards compatibility**; old direct-connect URLs without a ticket will receive `401 invalid_sse_ticket`.

---

## Why

`EventSource` (the browser's SSE client) **cannot attach custom headers**. That means JWT bearer tokens cannot be sent the way they are on normal API calls. To authenticate an SSE connection we use a short-lived, single-use ticket passed as a `?ticket=` query parameter.

Tickets are:

- **Short-lived** — 30 seconds (hardcoded in `settings.SSE_TICKET_TTL_SECONDS`).
- **Single-use** — consumed the first time the SSE connection is opened with them. Reconnects require a fresh ticket.
- **User-bound** — each ticket resolves to the JWT-authenticated user who requested it.
- **Stored in Redis** — the ticket itself is an opaque random string; no user info is encoded in it.

---

## New endpoint

### `POST /api/auth/sse-ticket/`

- **Auth:** standard JWT via `Authorization: Bearer <access>`.
- **Body:** none.
- **Response 200:**
  ```json
  { "ticket": "2f9a8c...opaque-random...", "expires_in": 30 }
  ```

`expires_in` is seconds until expiry.

---

## Updated SSE flow

### 1. Before opening an `EventSource`, fetch a ticket

```js
async function fetchSseTicket(accessToken) {
  const r = await fetch("/api/auth/sse-ticket/", {
    method: "POST",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!r.ok) throw new Error(`sse-ticket failed: ${r.status}`);
  const { ticket, expires_in } = await r.json();
  return { ticket, expiresIn: expires_in };
}
```

### 2. Open the SSE connection with the ticket appended

```js
async function openSessionStream(sessionId, accessToken) {
  const { ticket } = await fetchSseTicket(accessToken);
  const url = `/api/sessions/${sessionId}/stream?ticket=${encodeURIComponent(ticket)}`;
  return new EventSource(url);
}
```

### 3. On reconnect, fetch a fresh ticket

`EventSource` automatically retries on disconnect. Since the original ticket was consumed on the first successful connect, the retry will fail with `401 invalid_sse_ticket`. To handle this cleanly, close the old stream on error and open a new one with a new ticket:

```js
function connectWithAutoReconnect(sessionId, accessToken) {
  let es;
  let backoffMs = 1000;

  const connect = async () => {
    try {
      es = await openSessionStream(sessionId, accessToken);

      es.onopen = () => {
        backoffMs = 1000;
      };

      es.onerror = () => {
        es.close();
        // jittered exponential backoff up to 30s
        const delay = Math.min(backoffMs + Math.random() * 500, 30_000);
        backoffMs = Math.min(backoffMs * 2, 30_000);
        setTimeout(connect, delay);
      };

      // hook your own handlers for message/status/memory/fatal-error
    } catch (err) {
      setTimeout(connect, backoffMs);
      backoffMs = Math.min(backoffMs * 2, 30_000);
    }
  };

  connect();
  return () => es && es.close();
}
```

### 4. When the access token expires, refresh it *before* fetching the next ticket

If `POST /api/auth/sse-ticket/` returns `401`, the JWT is expired. Call `POST /api/auth/refresh/`, store the new access token, then retry the ticket request.

---

## Error shapes

| Status | Body | When |
|---|---|---|
| 401 | `{"status_code": 401, "code": "invalid_sse_ticket", "message": "Invalid or expired SSE ticket."}` | Missing, expired, or already-consumed ticket on an SSE URL. |
| 401 | standard DRF auth envelope | Bad JWT on `/api/auth/sse-ticket/`. |

The `text/event-stream` handshake never starts when the ticket is rejected; you get a normal JSON response with HTTP 401.

---

## Don't do these

- ❌ Don't pass the JWT itself as a query parameter. It ends up in server access logs and browser history.
- ❌ Don't cache tickets in `localStorage` / IndexedDB — they're single-use and very short-lived.
- ❌ Don't reuse a ticket across multiple `EventSource` instances — only the first one will authenticate.
- ❌ Don't skip the `onerror` → re-ticket path; without it a single network blip kills the stream forever.

---

## Server config knobs

| Setting | Value | Effect |
|---|---|---|
| `SSE_TICKET_TTL_SECONDS` | `30` (hardcoded in `settings.py`) | How long a freshly issued ticket is valid before consume. |

Tickets are stored in Redis via the raw `django_redis` client under the `rbac:sse_ticket:<token>` key. Consume uses `GETDEL` (Redis 6.2+) so get-and-delete is atomic — two simultaneous consumers cannot both succeed. They are not persisted to the database.

