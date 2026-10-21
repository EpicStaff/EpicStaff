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
plugin sees it, and adds the context in the `X-EpicStaff-Plugin-Context` header. Whatever value a
client sends in that header, in any spelling, is removed first. The plugin also never receives
the browser's cookies, and the browser never receives cookies the plugin sets.

In this version the gateway forwards only [public paths](../how-to/public-paths.md), with a
public context. Every other path is answered `401 login_required` until people can log in to
plugins.

## Format

A compact JWS (a signed JWT), signed with Ed25519.

**Header**

```json
{ "alg": "EdDSA", "typ": "epicstaff-plugin-context+jwt", "kid": "3f9c2a7b1e4d8a60" }
```

**Claims**

```json
{
  "iss": "https://epicstaff.example.com",
  "aud": "weather",
  "iat": 1792310400,
  "exp": 1792310460,
  "jti": "0d6f3c0b9a2e4f7d8c1b5a6e3f2d9c4b",
  "plugin": { "identifier": "weather", "version": "0.2.0" },
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
| `user` | `{id, email, name}` of the person making the request, or `null` |
| `permissions` | The plugin actions the person holds there (`read`, `update`, ...); `[]` when public |
| `request` | The request the context is for: its method and its canonical path, without the query string |
| `mode` | `public` on a public path: `org` and `user` are `null` and `permissions` is empty. `user` is reserved for requests from a logged-in person |

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
| `invalid_claims` | A claim is missing or breaks the format above |
| `request_mismatch` | Issued for another method or path |
| `dot_segment` | The path has a `.` or `..` segment |

Through the gateway these should not happen: every forwarded request has a fresh context for
exactly that request. Seeing them means either a clock far off on the node, a deployment whose
public address changed, or someone calling the plugin's port directly.

## Using the context in your app

```python
from epicstaff_plugin.gateway import context_from_scope
from fastapi import FastAPI, Request

app = FastAPI()


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}
```

`context_from_scope` takes any ASGI scope (`request.scope`, `websocket.scope`). In tests, sign
contexts with `epicstaff_plugin.testing.ContextSigner`; see the [Python SDK](python-sdk.md#testing).
