# Python SDK (`epicstaff-plugin`)

The Python package `epicstaff-plugin` (module `epicstaff_plugin`, in the EpicStaff repository at
`src/plugin_sdk`) is everything a plugin backend needs from the platform, and the
`epicstaff-plugin` command-line tool that validates, packs and signs plugins. It supports
Python 3.12 and 3.13.

| Module | What it is for |
|---|---|
| `epicstaff_plugin.serve` | The runner the node starts: health, hook dispatch, context check, uvicorn |
| `epicstaff_plugin.gateway` | Verifying the [gateway context](gateway-context.md) of each request |
| `epicstaff_plugin.hooks` | Registering [lifecycle hook](hook-api.md) handlers, verifying hook calls |
| `epicstaff_plugin.client` | Calling EpicStaff's API as the plugin's service account, alone or on behalf of a person |
| `epicstaff_plugin.runtime` | Reading the [runtime file](runtime.md#runtime-file): settings, addresses, keys |
| `epicstaff_plugin.health` | The `GET /_epicstaff/health` endpoint |
| `epicstaff_plugin.testing` | Forged contexts, hook calls and runtime files for your tests |
| `epicstaff_plugin.contracts` | The documents EpicStaff and plugins exchange, as Pydantic models |
| `epicstaff-plugin` (command) | `validate`, `pack`, `keygen`, `sign`, `verify`, `schema`; see [Sign and package a plugin](../how-to/sign-and-package.md) |

Until the package is published, a plugin's lock gets it from a wheel built from the repository;
[Sign and package a plugin](../how-to/sign-and-package.md#a-plugin-with-a-backend) shows how.

## A minimal backend

`plugin-samples/weather/backend/src/weather_plugin/app.py` is a complete one. In outline:

```python
from typing import Any

from epicstaff_plugin.gateway import context_from_scope
from epicstaff_plugin.runtime import runtime_config
from fastapi import FastAPI, Request

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.get("/api/whoami")
async def whoami(request: Request) -> dict[str, Any]:
    context = context_from_scope(request.scope)
    return context.model_dump(
        mode="json", include={"mode", "user", "org", "permissions", "request"}
    )


@app.get("/api/settings")
async def settings() -> dict[str, str | None]:
    return {"units": runtime_config().setting("units")}
```

with `"backend": {"python": "3.13", "entrypoint": "weather_plugin.app:app"}` in the manifest and
`/api/ping` declared as a public path. `/api/whoami` is reached only by a logged-in person, so its
context is always a user context. Turning off FastAPI's generated pages keeps the plugin's public
address to the routes you wrote.

## `epicstaff_plugin.serve`

```
python -I -m epicstaff_plugin.serve
```

What the node runs ([Runtime](runtime.md#how-the-backend-is-started)). It reads the runtime
file, imports the app `EPICSTAFF_PLUGIN_ENTRYPOINT` names (which registers your hook handlers),
and serves `HealthCheckMiddleware(HookDispatchMiddleware(EpicStaffContextMiddleware(app)))` with
uvicorn (one worker, no `Server` header, no proxy headers, lifespan on). So health answers
first, then hook calls, and every other request needs a gateway context. It serves on the listening socket the node passes as
the descriptor `EPICSTAFF_PLUGIN_LISTEN_FD` names, and binds `0.0.0.0:$PORT` itself only when
that variable is not set. It exits with status 1 and a line on standard error when the runtime
file or the entrypoint is missing or wrong, the descriptor is not a listening TCP socket, `PORT`
is wrong (without a descriptor), or uvicorn is not installed.

| Function | Use |
|---|---|
| `build_app(app, runtime, *, hooks=None, epicstaff=None)` | The wrapped app `serve` runs, for tests of your app as the node serves it. `hooks` replaces the process-wide `hook_registry`, and `epicstaff` the `EpicStaffClient` hook handlers get (by default a new one over `runtime`) |
| `load_entrypoint("module.path:attribute")` | Import an ASGI app by its entrypoint; raises `ServeError` |
| `inherited_listen_fd()` | The node's listening socket from `EPICSTAFF_PLUGIN_LISTEN_FD`, checked and made non-inheritable, or `None`; raises `ServeError` |

To run your backend on your machine the way the node does, write a runtime file with
`epicstaff_plugin.testing.write_runtime_file` and set the variables of [Runtime](runtime.md#environment).

## `epicstaff_plugin.gateway`

| Name | What it does |
|---|---|
| `context_from_scope(scope) -> GatewayContext` | The verified context of the request whose ASGI scope this is. Raises `ContextUnavailableError` when the app runs without the middleware |
| `EpicStaffContextMiddleware(app, verifier=None)` | ASGI middleware for HTTP and WebSocket: lets a request through only with a valid context, which it puts in the scope; answers others `401 {"code":"context_invalid"}`. Lifespan events pass through. Without a `verifier` it uses the process's runtime file |
| `ContextVerifier(runtime, *, fetch_jwks=None)` | The checks of [Verification](gateway-context.md#verification). `verify(token, method, path)` returns the `GatewayContext` or raises `ContextRejected`; `verify_async(...)` is the same for use inside an event loop. `fetch_jwks(url) -> bytes` replaces the JWKS download (default: an HTTP GET with a 2 s timeout, never through a proxy) |
| `ContextRejected` | `.reason` names the failed check; [the list](gateway-context.md#when-a-context-is-refused) |

`GatewayContext` (from `epicstaff_plugin.contracts.gateway_context`) has the claims as
attributes: `context.mode`, `context.user.email`, `context.org.id`, `context.permissions`,
`context.request.path`, and so on; `context.model_dump(mode="json")` gives the claims as a
dictionary. Two predicates answer the usual questions:

| Predicate | Answer |
|---|---|
| `context.is_user` | `True` when a logged-in person makes the request (`mode` is `user`); `context.user` and `context.org` are then set and `permissions` contains `read`. `False` on a public path |
| `context.has_permission(action)` | Whether the person holds the plugin action `action` (`"read"`, `"create"`, `"update"`, `"delete"`, `"export"`, `"use"`) in the request's organization; always `False` in a public context. Any other name raises `ValueError`, so a misspelt check fails loudly instead of refusing everyone |

The gateway lets a person in on `read` alone, so check finer actions yourself:
`if not context.has_permission("update"): ...`. What `401 login_required` and `403 forbidden` from
the gateway mean is in [Gateway context](gateway-context.md#who-is-asking-user-contexts).

## `epicstaff_plugin.runtime`

| Name | What it does |
|---|---|
| `runtime_config() -> RuntimeConfig` | The process's runtime configuration, read once from `EPICSTAFF_PLUGIN_RUNTIME_FILE` and shared with the context check |
| `RuntimeConfig.load(path=None)` | Read a runtime file, by default the one the variable names |
| `RuntimeConfigError` | The variable is unset, or the file is unreadable or invalid. The message never contains setting values |

`RuntimeConfig` reads the file again whenever it changes (the node replaces it when EpicStaff's
keys rotate). If a later version of the file cannot be read, it logs a warning and keeps the
last good one.

| Attribute or method | Value |
|---|---|
| `setting(key, default=None)` | A non-secret setting: its value, its manifest default, or `default` |
| `secret_setting(key)` | A secret setting, or `None` when it is not set |
| `settings`, `secret_settings` | All of them, as read-only mappings |
| `plugin_identifier`, `plugin_version` | The running plugin |
| `public_url` | The plugin's public address: build external callback addresses from it |
| `epicstaff_public_url`, `epicstaff_api_url`, `issuer` | EpicStaff's addresses and context issuer |
| `service_account(org_id)` | The plugin's service account in the organization (`key`, `org_name`, `grant_state`), or `None`. Read it per call: keys rotate |
| `jwks`, `public_paths`, `service_accounts` | As in the runtime file |
| `document` | The whole `RuntimeFile`. It holds secrets: never log it |

## `epicstaff_plugin.health`

`HealthCheckMiddleware(app)` answers `GET /_epicstaff/health` with `200 {"status":"ok"}` and
passes everything else to `app`. `serve` puts it in front of the hook dispatch and the context
check; you never need it yourself. nginx does not forward `/_epicstaff/` from outside.

## `epicstaff_plugin.hooks`

| Name | What it does |
|---|---|
| `hook_registry` | The process's `HookRegistry`, which `serve` dispatches to |
| `hook_registry.on_install(handler)` | Registers the install hook; usable as a decorator. `on_upgrade` and `on_org_removed` register the other kinds, `register(kind, handler)` any kind. A kind takes one handler (`ValueError` for a second one); a handler is an async function (`TypeError` otherwise) |
| `HookDispatchMiddleware(app, verifier, registry, epicstaff)` | ASGI middleware that answers `POST` on the hook paths: verifies the call, runs the handler, answers as the [Hook API](hook-api.md#the-answer) says. Every other request goes to `app`. `serve` installs it |
| `verify_hook_assertion(assertion, body, *, kind, jwks, issuer, plugin_identifier)` | The checks of [Verification](hook-api.md#verification), outside the runner. Returns `VerifiedHook(claims, request)` or raises `HookAssertionRejected` |
| `HookAssertionRejected` | `.reason` names the failed check |

A handler is `async def handler(request: HookRequest, epicstaff: OrgClient) -> None`. `request`
is the verified body; `epicstaff` is the client for `request.org.id`, acting as the plugin
alone. Return to succeed; raise to fail, with the exception's first line as the error. Handlers
for one organization run one at a time. [Write an install hook](../how-to/install-hook.md) walks
through one.

## `epicstaff_plugin.client`

| Name | What it does |
|---|---|
| `EpicStaffClient(runtime=None, *, transport=None, timeout_seconds=30, person_cache_seconds=30)` | The client; one per process. `runtime` defaults to `runtime_config()`; `transport` replaces the HTTP transport (an `httpx.MockTransport` in tests). Use it as `async with`, or call `aclose()` |
| `client.for_org(org_id)` | The `OrgClient` for an organization, acting as the plugin alone |
| `client.client_for_context(context)` | `for_org(context.org.id).on_behalf_of(context.user.id)`; `ValueError` for a public context |
| `org.on_behalf_of(user_id)` | The same organization, on behalf of a person (`X-EpicStaff-On-Behalf-Of`) |
| `org.get(path, *, params=None)`, `post(path, json)`, `put(path, json)`, `patch(path, json)`, `delete(path)` | Call a path under EpicStaff's API (`graphs/` is `/api/graphs/`); return the decoded JSON answer, `None` when empty |
| `org.request(method, path, *, params, json, content, headers)` | The same, returning the `httpx.Response` |
| `org.me()` | `ServiceAccountInfo` |
| `org.person(user_id)`, `org.people(user_ids)` | `PluginPerson` or `None`; the eligible people, sorted by id |
| `org.run_flow(graph_id, variables)` | Starts a run; returns its session id |
| `org.session(session_id)`, `org.wait_for_session(session_id, *, timeout, poll_seconds=2)` | `FlowSession` (`id`, `status`, `finished`, `succeeded`, `variables`, `document`) |
| `org.upload_file(folder, filename, content)` | Stores bytes in the organization's storage |
| `EpicStaffApiError` | EpicStaff answered 400 or more: `status`, `code`, `message`, `errors` |
| `ServiceAccountUnavailable` | The runtime file holds no key for the organization: `org_id` |

The client never uses a proxy, never follows redirects, reads the organization's key from the
runtime file on every call, and retries a 401 once when the key has been replaced since. Its
behaviour, and what on behalf of means, is in
[Call EpicStaff from your backend](../how-to/call-epicstaff-from-the-backend.md).

## Testing

`epicstaff_plugin.testing` stands in for EpicStaff in your tests. It signs with keys it makes
itself, which no EpicStaff trusts, so never import it in production code.

| Name | What it does |
|---|---|
| `ContextSigner(plugin_identifier="sample", plugin_version="0.1.0", issuer="https://epicstaff.test")` | A gateway with its own Ed25519 key |
| `signer.headers(method, path, **fields)` | `{"X-EpicStaff-Plugin-Context": <token>}` for a request; `fields` as for `context` |
| `signer.issue(method, path, **fields)` | Just the token |
| `signer.context(method, path, *, mode="public", user=None, org=None, permissions=None, issued_at=None, lifetime_seconds=60)` | The `GatewayContext` it would sign. With `mode="user"`, whichever of `user`, `org` and `permissions` is not given becomes a test member (`epicstaff_plugin.testing.DEFAULT_USER`), a test organization (`DEFAULT_ORGANIZATION`) and `["read"]`. A context that breaks the rules of its mode raises `pydantic.ValidationError` |
| `signer.sign_claims(claims, headers=None)` | Signs any claims, for tests of contexts that must be refused |
| `signer.jwks` | Its public key, as a `Jwks` |
| `write_runtime_file(path, *, signer=None, **fields)` | Writes a valid runtime file whose plugin, issuer and JWKS are the signer's; `fields` replace top-level fields, such as `settings={"units": "imperial"}` or `service_accounts={"3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "active"}}` |
| `service_account_key()` | A new key in the form EpicStaff gives service accounts |
| `HookSigner(signer)` | Signs hook calls with the signer's key, as EpicStaff signs them with its context key |
| `HookSigner(signer).call(kind, *, org=None, job_id=1, attempt=1, previous_version=None, timeout_seconds=None, issued_at=None)` | A `HookCall` with `path`, `headers`, `body` (bytes), `request` and `claims`: post `body` to `path` with `headers` |
| `HookSigner(signer).sign(claims, headers=None)` | Signs any claims as a hook assertion, for tests of calls that must be refused |

A test of the Weather sample, served as the node serves it:

```python
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import ContextSigner, write_runtime_file
from fastapi.testclient import TestClient
from weather_plugin.app import app


def test_ping_is_public_and_whoami_names_the_person(tmp_path, monkeypatch):
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.3.0")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    client = TestClient(build_app(app, RuntimeConfig.load(runtime_file)))

    assert client.get("/api/ping", headers=signer.headers("GET", "/api/ping")).json() == {
        "status": "ok",
        "mode": "public",
    }
    assert client.get("/api/ping").status_code == 401

    ada = {"id": 42, "email": "ada@acme.example.com", "name": "Ada"}
    headers = signer.headers(
        "GET", "/api/whoami", mode="user", user=ada, org={"id": 3, "name": "Acme"}
    )
    assert client.get("/api/whoami", headers=headers).json()["user"] == ada
```

(`TestClient` needs `httpx` in your test dependencies.)

## `epicstaff_plugin.contracts`

The documents of the platform, defined once and used by EpicStaff and the SDK alike:

| Model | Document |
|---|---|
| `contracts.manifest.PluginManifest` | `manifest.json` ([reference](manifest.md)) |
| `contracts.gateway_context.GatewayContext`, `Jwks`, `Jwk` | The gateway context and its keys ([reference](gateway-context.md)) |
| `contracts.runtime.RuntimeFile`, `ServiceAccountEntry` | The runtime file ([reference](runtime.md#runtime-file)) |
| `contracts.hook_api.HookRequest`, `HookAssertionClaims`, `HookResponse`, `HOOK_PATHS` | Hook calls ([reference](hook-api.md)) |
| `contracts.service_account_api.ServiceAccountInfo`, `PluginPerson`, `PeopleLookupRequest`, `PeopleLookupResponse` | What EpicStaff's `/api/plugin-runtime/` endpoints answer ([reference](service-account-api.md)) |

Each model refuses unknown fields, so whoever builds a document cannot misspell one. Read a
document from a newer EpicStaff leniently with `Model.model_validate_json(raw, extra="ignore")`,
as the SDK does.
