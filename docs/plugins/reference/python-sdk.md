# Python SDK (`epicstaff-plugin`)

The Python package `epicstaff-plugin` (module `epicstaff_plugin`, in the EpicStaff repository at
`src/plugin_sdk`) is everything a plugin backend needs from the platform, and the
`epicstaff-plugin` command-line tool that validates, packs and signs plugins. It supports
Python 3.12 and 3.13.

| Module | What it is for |
|---|---|
| `epicstaff_plugin.serve` | The runner the node starts: health, context check, uvicorn |
| `epicstaff_plugin.gateway` | Verifying the [gateway context](gateway-context.md) of each request |
| `epicstaff_plugin.runtime` | Reading the [runtime file](runtime.md#runtime-file): settings, addresses, keys |
| `epicstaff_plugin.health` | The `GET /_epicstaff/health` endpoint |
| `epicstaff_plugin.testing` | Forged contexts and runtime files for your tests |
| `epicstaff_plugin.contracts` | The documents EpicStaff and plugins exchange, as Pydantic models |
| `epicstaff-plugin` (command) | `validate`, `pack`, `keygen`, `sign`, `verify`, `schema`; see [Sign and package a plugin](../how-to/sign-and-package.md) |

Until the package is published, a plugin's lock gets it from a wheel built from the repository;
[Sign and package a plugin](../how-to/sign-and-package.md#a-plugin-with-a-backend) shows how.

## A minimal backend

`plugin-samples/weather/backend/src/weather_plugin/app.py` is a complete one. In outline:

```python
from epicstaff_plugin.gateway import context_from_scope
from epicstaff_plugin.runtime import runtime_config
from fastapi import FastAPI, Request

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/api/ping")
async def ping(request: Request) -> dict[str, str]:
    return {"status": "ok", "mode": context_from_scope(request.scope).mode}


@app.get("/api/settings")
async def settings() -> dict[str, str | None]:
    return {"units": runtime_config().setting("units")}
```

with `"backend": {"python": "3.13", "entrypoint": "weather_plugin.app:app"}` in the manifest.
Turning off FastAPI's generated pages keeps the plugin's public address to the routes you wrote.

## `epicstaff_plugin.serve`

```
python -I -m epicstaff_plugin.serve
```

What the node runs ([Runtime](runtime.md#how-the-backend-is-started)). It reads the runtime
file, imports the app `EPICSTAFF_PLUGIN_ENTRYPOINT` names, and serves
`HealthCheckMiddleware(EpicStaffContextMiddleware(app))` with uvicorn (one worker, no `Server`
header, no proxy headers, lifespan on). It serves on the listening socket the node passes as
the descriptor `EPICSTAFF_PLUGIN_LISTEN_FD` names, and binds `0.0.0.0:$PORT` itself only when
that variable is not set. It exits with status 1 and a line on standard error when the runtime
file or the entrypoint is missing or wrong, the descriptor is not a listening TCP socket, `PORT`
is wrong (without a descriptor), or uvicorn is not installed.

| Function | Use |
|---|---|
| `build_app(app, runtime)` | The wrapped app `serve` runs, for tests of your app as the node serves it |
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
dictionary.

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
| `jwks`, `public_paths`, `service_accounts` | As in the runtime file |
| `document` | The whole `RuntimeFile`. It holds secrets: never log it |

## `epicstaff_plugin.health`

`HealthCheckMiddleware(app)` answers `GET /_epicstaff/health` with `200 {"status":"ok"}` and
passes everything else to `app`. `serve` puts it in front of the context check; you never need
it yourself. nginx does not forward `/_epicstaff/` from outside.

## Testing

`epicstaff_plugin.testing` stands in for EpicStaff in your tests. It signs with keys it makes
itself, which no EpicStaff trusts, so never import it in production code.

| Name | What it does |
|---|---|
| `ContextSigner(plugin_identifier="sample", plugin_version="0.1.0", issuer="https://epicstaff.test")` | A gateway with its own Ed25519 key |
| `signer.headers(method, path, **fields)` | `{"X-EpicStaff-Plugin-Context": <token>}` for a request; `fields` as for `context` |
| `signer.issue(method, path, **fields)` | Just the token |
| `signer.context(method, path, *, mode="public", user=None, org=None, permissions=(), issued_at=None, lifetime_seconds=60)` | The `GatewayContext` it would sign |
| `signer.sign_claims(claims, headers=None)` | Signs any claims, for tests of contexts that must be refused |
| `signer.jwks` | Its public key, as a `Jwks` |
| `write_runtime_file(path, *, signer=None, **fields)` | Writes a valid runtime file whose plugin, issuer and JWKS are the signer's; `fields` replace top-level fields, such as `settings={"units": "imperial"}` |

A test of the Weather sample, served as the node serves it:

```python
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import ContextSigner, write_runtime_file
from fastapi.testclient import TestClient
from weather_plugin.app import app


def test_ping_is_public(tmp_path, monkeypatch):
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.2.0")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    client = TestClient(build_app(app, RuntimeConfig.load(runtime_file)))

    assert client.get("/api/ping", headers=signer.headers("GET", "/api/ping")).json() == {
        "status": "ok",
        "mode": "public",
    }
    assert client.get("/api/ping").status_code == 401
```

(`TestClient` needs `httpx` in your test dependencies.)

## `epicstaff_plugin.contracts`

The documents of the platform, defined once and used by EpicStaff and the SDK alike:

| Model | Document |
|---|---|
| `contracts.manifest.PluginManifest` | `manifest.json` ([reference](manifest.md)) |
| `contracts.gateway_context.GatewayContext`, `Jwks`, `Jwk` | The gateway context and its keys ([reference](gateway-context.md)) |
| `contracts.runtime.RuntimeFile` | The runtime file ([reference](runtime.md#runtime-file)) |

Each model refuses unknown fields, so whoever builds a document cannot misspell one. Read a
document from a newer EpicStaff leniently with `Model.model_validate_json(raw, extra="ignore")`,
as the SDK does.
