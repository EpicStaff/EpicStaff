# Gateway context

Every request that reaches a plugin's backend through EpicStaff carries a **gateway context**: a
short-lived statement, signed by EpicStaff, of which request it is for and who is making it. The
plugin verifies it with EpicStaff's public keys. It can read the context but never forge one,
and neither can anyone else, including other plugins on the same node.

This page describes version 1 of the context (`platform.gateway_context: 1` in the manifest). The
[Python SDK](python-sdk.md) verifies it for you; `epicstaff_plugin.serve` refuses every request
without a valid context before it reaches your app.

## How a request reaches the plugin

```
browser ── https://weather.plugins.example.com/api/ping ──▶ EpicStaff's gateway
                                                           │ 1. is this plugin running?
                                                           │ 2. is the path canonical?
                                                           │ 3. public path, or a logged-in person?
                                                           ▼
                        plugin process ◀── same request + X-EpicStaff-Plugin-Context: <signed context>
```

The gateway decides every request to `https://<id>.<plugins base domain>/api/**` before the
plugin sees it, and adds the context in the `X-EpicStaff-Plugin-Context` header. While the
plugin is stopped for an upgrade, it refuses every path, public ones included, with the deny
reason `maintenance` (the client gets `503 plugin_maintenance`); once the plugin is back, it
gives the same answer to a member of an organization whose upgrade hook has not finished, and
`plugin_unavailable` to one whose upgrade failed ([Error codes](error-codes.md#gateway-codes)). Whatever value a
client sends in that header, in any spelling, is removed first. The plugin also never receives
the browser's cookies, and the browser never receives cookies the plugin sets.

A request gets one of two kinds of context:

- **Public**, on a [public path](../how-to/public-paths.md) the manifest declares: no person, no
  organization, no permissions. Anyone can make these requests, logged in or not.
- **User**, on every other path: the request comes from a person logged in to EpicStaff through
  the plugin's page. The [JS SDK](js-sdk.md) logs the person in and sends the plugin login
  token it gets ([token exchange](token-exchange.md)) as `Authorization: Bearer <token>` on the
  plugin's own `/api/` calls. The gateway checks the token and the person's access, then
  forwards the request with a user context. The plugin never sees the token.

## Who is asking: user contexts

The gateway forwards a request on a non-public path only when all of these hold, checked in this
order:

1. it carries a valid plugin login token for this plugin, unexpired and not altered;
2. the person's account is active, and their password has not changed since the token was
   issued;
3. the person is still a member of the organization the token was issued in, and the
   organization is active;
4. the plugin is still granted to that organization, the grant is active, and it is not being
   upgraded there;
5. the person's role there includes the plugin's `read` action.

Before any of them, the plugin itself must be up: while it is stopped for an upgrade, every path
is answered `503 plugin_maintenance`, signed in or not. Otherwise the gateway answers instead of
the plugin, in EpicStaff's error shape:

| Answer | Meaning | What the JS SDK does |
|---|---|---|
| `401 login_required` | The request has no acceptable token: none, expired, for another plugin, or no longer valid (checks 1 and 2, or a grant that was suspended, deleted or re-created in check 4) | Renews the token silently, once, and repeats the request |
| `403 forbidden` | The token is fine, but the person may no longer use the plugin in that organization (checks 3 and 5) | Reports that the person has no access, and does not retry |
| `503 plugin_maintenance` | The plugin is stopped for an upgrade, or the person's organization is still being upgraded (checks 1 to 3 hold, and the grant is `upgrading`). Comes with `Retry-After: 30` | Reports `availability: maintenance`, and does not renew the token |
| `503 plugin_unavailable` | The person's organization's upgrade failed (checks 1 to 3 hold, and the grant is `upgrade_failed`), or the plugin's process is not up | Reports `availability: unavailable` |

So someone who is no longer a member of an organization learns nothing about its upgrade.

A change to an account, a membership, a role or a grant takes effect within 10 seconds. The token
itself lives at most 15 minutes and is not ended by logging out of EpicStaff.

The plugin never receives a credential for EpicStaff:

- **The plugin login token** never reaches the plugin process. The gateway removes
  `Authorization` on every non-public path, and on a public path when it holds a plugin login
  token, whose context then stays public.
- **EpicStaff's cookies and API keys** are removed before every request.

On a public path any other `Authorization` header is passed through, so a plugin can check
tokens it issued itself. The context is the only statement of who is asking; nothing the plugin
receives lets it act in EpicStaff as that person.

The gateway lets a person in on `read` alone. Any finer action (`update`, `delete`, ...) is the
plugin's own check: `context.has_permission("update")`.

A browser cannot set `Authorization` on a WebSocket, so a WebSocket from the plugin's page
reaches the backend only on a public path ([frontend in the
frame](../how-to/frontend-in-the-frame.md)).

## Format

A compact JWS (a signed JWT), signed with Ed25519.

**Header**

```json
{ "alg": "EdDSA", "typ": "epicstaff-plugin-context+jwt", "kid": "3f9c2a7b1e4d8a60" }
```

**Claims** of a user context

```json
{
  "iss": "https://epicstaff.example.com",
  "aud": "weather",
  "iat": 1792310400,
  "exp": 1792310460,
  "jti": "0d6f3c0b9a2e4f7d8c1b5a6e3f2d9c4b",
  "plugin": { "identifier": "weather", "version": "0.3.0" },
  "org": { "id": 3, "name": "Acme" },
  "user": { "id": 42, "email": "ada@acme.example.com", "name": "Ada" },
  "permissions": ["read"],
  "request": { "method": "GET", "path": "/api/whoami" },
  "mode": "user"
}
```

and of a public context

```json
{
  "iss": "https://epicstaff.example.com",
  "aud": "weather",
  "iat": 1792310400,
  "exp": 1792310460,
  "jti": "7a1e5c9d3b2f4e6a8c0d1b3f5e7a9c2d",
  "plugin": { "identifier": "weather", "version": "0.3.0" },
  "org": null,
  "user": null,
  "permissions": [],
  "request": { "method": "GET", "path": "/api/ping" },
  "mode": "public"
}
```

| Claim | Meaning |
|---|---|
| `iss` | EpicStaff's public origin; equals the runtime file's `issuer` |
| `aud` | The plugin's id; the context is for this plugin only |
| `iat`, `exp` | Issued at and expiry, in Unix seconds; `exp` = `iat` + 60 |
| `jti` | 32 random hex characters, unique per context |
| `plugin` | The plugin's id and the version EpicStaff routed the request to |
| `org` | `{id, name}` of the organization the request is made in, or `null` |
| `user` | `{id, email, name}` of the person making the request, or `null`. `name` is the name EpicStaff shows for them |
| `permissions` | The plugin actions the person holds there (`read`, `update`, ...), in the order of the manifest's `user_permissions`; `[]` when public |
| `request` | The request the context is for: its method and its canonical path, without the query string |
| `mode` | `user` for a logged-in person: `org` and `user` are set and `permissions` contains `read`. `public` on a public path: `org` and `user` are `null` and `permissions` is empty |

Each `mode` comes only with its own shape: a context that breaks it is refused
(`invalid_claims`).

The models are `epicstaff_plugin.contracts.gateway_context.GatewayContext` and its parts. A
newer EpicStaff may add claims; ignore claims you do not know.

## Verification

A context is valid when **all** of these hold, which is exactly what the SDK's
`ContextVerifier` checks:

1. The header's `typ` is `epicstaff-plugin-context+jwt` and its `alg` is `EdDSA`.
2. The signature verifies with the public key whose `kid` the header names, from the JWKS.
3. `aud` is the plugin's own id.
4. `iss` is the runtime file's `issuer`.
5. `exp` has not passed, allowing 30 s for clocks that disagree; `iat` is not more than 30 s in
   the future.
6. `request.method` equals the method of the request the context came with (`GET` for a
   WebSocket handshake), and `request.path` equals its path as the ASGI server decoded it
   (`scope["path"]`).
7. The path has no `.` or `..` segment.

Binding the context to the method and path means a context seen once cannot be reused for
another request; its 60-second life bounds how long it can be reused for the same one.

### Keys

EpicStaff publishes its keys as a JWKS:

```json
{ "keys": [ { "kty": "OKP", "crv": "Ed25519", "x": "<base64url of the 32-byte public key>", "kid": "3f9c2a7b1e4d8a60", "alg": "EdDSA", "use": "sig" } ] }
```

The same document is in the runtime file (`jwks`) and at `GET <EPICSTAFF_API_URL>plugin-public/jwks/`.
EpicStaff signs with its newest key; when an operator rotates it, the previous key stays in the
JWKS for 24 hours, and the node rewrites every runtime file with the new set. A context whose
`kid` is not in the runtime file makes the SDK read the file again and then download the JWKS,
at most once every 30 seconds; a downloaded key is trusted only until the runtime file changes or
for 10 minutes, so a retired key does not stay trusted.

## When a context is refused

`epicstaff_plugin.serve` answers a request without a valid context with

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"code":"context_invalid"}
```

and a WebSocket handshake with the same response (or, on servers that cannot send one, by
closing it with code 1008). The plugin's log names the failed check, never the token:

```
Refused GET '/api/ping': gateway context expired
```

| Reason in the log | Meaning |
|---|---|
| `missing`, `ambiguous` | No `X-EpicStaff-Plugin-Context` header, or more than one |
| `malformed` | Not a JWS, too long, another algorithm, or no usable `kid` |
| `wrong_type` | The header's `typ` is not `epicstaff-plugin-context+jwt` |
| `unknown_key` | No key with that `kid`, even after downloading the JWKS |
| `bad_signature` | The signature does not verify: the token was altered or signed by someone else |
| `expired`, `not_yet_valid` | Outside its lifetime, beyond the 30 s allowance |
| `wrong_audience`, `wrong_issuer` | Issued for another plugin, or by another EpicStaff |
| `invalid_claims` | A claim is missing or breaks the format above, such as a user context without `read` |
| `request_mismatch` | Issued for another method or path |
| `dot_segment` | The path has a `.` or `..` segment |

Through the gateway these should not happen: every forwarded request has a fresh context for
exactly that request. Seeing them means either a clock far off on the node, a deployment whose
public address changed, or someone calling the plugin's port directly.

## Using the context in your app

```python
from epicstaff_plugin.gateway import context_from_scope
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.delete("/api/places/{place_id}")
async def delete_place(place_id: int, request: Request) -> None:
    context = context_from_scope(request.scope)
    if not context.has_permission("delete"):
        raise HTTPException(403)
    ...  # delete the place of context.org.id
```

| On `GatewayContext` | Value |
|---|---|
| `is_user` | `True` for a user context: `user` and `org` are set |
| `has_permission(action)` | Whether the person holds `action` (`"read"`, `"update"`, ...); always `False` in a public context. An action name that does not exist raises `ValueError` |

`context_from_scope` takes any ASGI scope (`request.scope`, `websocket.scope`). Scope everything a
person reads or changes to `context.org.id`: the same person may use the plugin in several
organizations. In tests, sign contexts with `epicstaff_plugin.testing.ContextSigner`; see the
[Python SDK](python-sdk.md#testing).
