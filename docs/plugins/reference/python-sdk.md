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
| `epicstaff_plugin.database` | The plugin's own [database](database.md): its address, its connection limit, a transaction per organization |
| `epicstaff_plugin.egress` | The egress proxy, for clients that do not read it from the environment ([outbound hosts](../how-to/outbound-hosts.md)) |
| `epicstaff_plugin.health` | The `GET /_epicstaff/health` endpoint |
| `epicstaff_plugin.versions` | Comparing plugin versions in SemVer order, as EpicStaff does: an upgrade hook compares `previous_version` with it |
| `epicstaff_plugin.testing` | Forged contexts, hook calls and runtime files for your tests |
| `epicstaff_plugin.contracts` | The documents EpicStaff and plugins exchange, as Pydantic models |
| `epicstaff-plugin` (command) | `validate`, `pack`, `keygen`, `sign`, `verify`, `schema` and `dev`; see the [command-line reference](cli.md) |

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
| `create_app()` | The app `serve` runs, built from the environment: it reads the runtime file `EPICSTAFF_PLUGIN_RUNTIME_FILE` names, imports the app `EPICSTAFF_PLUGIN_ENTRYPOINT` names, and returns `build_app(app, runtime)`. Raises `RuntimeConfigError` when the runtime file is not named, unreadable or invalid, and `ServeError` when the entrypoint is not set or does not import. [`epicstaff-plugin dev`](cli.md#epicstaff-plugin-dev) serves it too, as a uvicorn app factory, so a backend runs on your machine exactly as the node composes it |
| `build_app(app, runtime, *, hooks=None, epicstaff=None)` | The wrapped app `serve` runs, for tests of your app as the node serves it. `hooks` replaces the process-wide `hook_registry`, and `epicstaff` the `EpicStaffClient` hook handlers get (by default a new one over `runtime`) |
| `load_entrypoint("module.path:attribute")` | Import an ASGI app by its entrypoint; raises `ServeError` |
| `inherited_listen_fd()` | The node's listening socket from `EPICSTAFF_PLUGIN_LISTEN_FD`, checked and made non-inheritable, or `None`; raises `ServeError` |

To run your backend on your machine against a local EpicStaff, use
[`epicstaff-plugin dev`](cli.md#epicstaff-plugin-dev) ([Local
development](../how-to/local-development.md#develop-the-backend-on-your-machine)). In tests, serve
`build_app` with a runtime file from `epicstaff_plugin.testing.write_runtime_file`
([Testing](#testing)).

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

## `epicstaff_plugin.database`

For a backend whose manifest has a `database` section ([Plugin database](database.md)). The SDK
depends on no database driver: bring one, such as `psycopg[binary,pool]`, in your lock.

| Name | What it does |
|---|---|
| `database_url() -> str` | `DATABASE_URL`: the database's URL, logging in as the app role. Raises `DatabaseUnavailable` when it is not set. It holds the role's password: never log it |
| `connection_limit() -> int` | `EPICSTAFF_PLUGIN_DB_CONNECTIONS`: how many connections the app role may hold. Raises `DatabaseUnavailable` when it is not set or not a positive integer. Size your pool to it |
| `org_transaction(connection, org_id)` | An async context manager. It opens `connection.transaction()`, runs `SELECT pg_catalog.set_config('app.org_id', %s, true)` with `(str(org_id),)`, and yields the connection. The setting lasts for the transaction only. The transaction commits when the block ends and rolls back when it raises. Raises `ValueError` when `org_id` is not a positive integer. One organization at a time in a task: nested inside an open one for the same organization it is a savepoint on the same connection, or a transaction of its own on a connection with none open; for another organization, or inside a `job_transaction`, it raises `NestedOrgTransactionError`, on any connection. A task started inside the block inherits its organization while the block is open; once the block ended, the task has none, and the block's connection, which the pool may have lent to another request, is no longer its own |
| `job_transaction(connection)` | An async context manager for maintenance work across organizations. It opens `connection.transaction()`, switches to the plugin's job role for that transaction only (`SELECT pg_catalog.set_config('role', %s, true)` with `<id_>_job`, named after the `<id_>_app` role the connection logs in as), and yields the connection. The transaction has exactly what your migrations grant `${job_role}`, and no organization set. Raises `ValueError` when the connection does not log in as the app role, and `NestedOrgTransactionError` inside an `org_transaction`. Nested in an open one, on the same connection, it is a savepoint. A task started inside the block inherits it while the block is open |
| `ORG_ID_SETTING` | `"app.org_id"`, the setting your row-level security policies read with `current_setting('app.org_id', true)` |
| `APP_ROLE_SUFFIX`, `JOB_ROLE_SUFFIX` | `"_app"` and `"_job"`, the endings of the role names ([Names](database.md#names)) |
| `DatabaseUnavailable` | The process has no database: its manifest declares none, or it runs off the plugin node |
| `NestedOrgTransactionError` | An `org_transaction` for another organization, or an `org_transaction` and a `job_transaction` inside each other, opened while the other is open in the task |
| `ConnectionInTransactionError` | The connection already has a transaction open that no open block of the task started on it. psycopg opens one by itself for any query outside a transaction block. The organization or role would outlive the block, since a savepoint does not end it, so the block refuses the connection. Use a fresh connection from the pool |
| `AsyncTransactionalConnection` | What the two helpers need of a connection: `transaction()`, `async execute(query, params)`, and `info.transaction_status` and `info.user`. psycopg 3's `AsyncConnection` has them all |

Every `ValueError`, `NestedOrgTransactionError` and `ConnectionInTransactionError` is raised
before anything is sent to the database.

With psycopg's pool, opened in your app's lifespan:

```python
from epicstaff_plugin.database import connection_limit, database_url, org_transaction
from psycopg_pool import AsyncConnectionPool

pool = AsyncConnectionPool(database_url(), min_size=1, max_size=connection_limit(), open=False)
await pool.open(wait=True)

async with pool.connection() as connection, org_transaction(connection, context.org.id):
    cursor = await connection.execute("SELECT id, name FROM places.saved ORDER BY name")
```

A maintenance task deletes expired rows of every organization in a `job_transaction`, under the
job role's own policies:

```python
from epicstaff_plugin.database import job_transaction

async with pool.connection() as connection, job_transaction(connection):
    await connection.execute(
        "DELETE FROM places.lookups WHERE looked_up_at < now() - interval '1 day'"
    )
```

`plugin-samples/weather/backend/src/weather_plugin/database.py` is a complete one, and
`plugin-samples/weather/backend/src/weather_plugin/retention.py` a maintenance task.
[Write database migrations](../how-to/database-migrations.md) shows the policies that go with
both.

## `epicstaff_plugin.egress`

Every backend's environment names the egress proxy, and clients that read the environment use it
with no code (httpx, requests, `urllib.request`; aiohttp with `trust_env=True`). For the others:

| Name | What it does |
|---|---|
| `proxy_url() -> str` | `HTTPS_PROXY`: the egress proxy's URL, with the plugin's own credentials. Raises `EgressProxyUnavailable` when it is not set. Never log it |
| `HTTPS_PROXY_ENVIRONMENT_VARIABLE` | `"HTTPS_PROXY"`, from `epicstaff_plugin.contracts.runtime` |
| `EgressProxyUnavailable` | `HTTPS_PROXY` is not set: the process runs off the plugin node |

```python
import aiohttp
from epicstaff_plugin.egress import proxy_url

async with aiohttp.ClientSession() as session:
    async with session.get("https://api.example.com/v1/items", proxy=proxy_url()) as response:
        ...
```

## `epicstaff_plugin.health`

`HealthCheckMiddleware(app)` answers `GET /_epicstaff/health` with `200 {"status":"ok"}` and
passes everything else to `app`. `serve` puts it in front of the hook dispatch and the context
check; you never need it yourself. nginx does not forward `/_epicstaff/` from outside.

## `epicstaff_plugin.hooks`

| Name | What it does |
|---|---|
| `hook_registry` | The process's `HookRegistry`, which `serve` dispatches to |
| `hook_registry.on_install(handler)` | Registers the install hook; usable as a decorator |
| `hook_registry.on_upgrade(handler)` | Registers the upgrade hook; usable as a decorator. Its handler takes the request and an `OrgClient`, like the install hook's |
| `hook_registry.on_org_removed(handler)` | Registers the organization removed hook, whose handler takes the request alone; usable as a decorator |
| `hook_registry.register(kind, handler)` | Registers any kind. A kind takes one handler (`ValueError` for a second one). A handler is an async function that can be called with its kind's arguments (`TypeError` otherwise, at registration) |
| `OrgHookHandler`, `OrgRemovedHookHandler` | The two handler types: `async (request, epicstaff) -> None` for `install` and `upgrade`, `async (request) -> None` for `org_removed` |
| `HookDispatchMiddleware(app, verifier, registry, epicstaff)` | ASGI middleware that answers `POST` on the hook paths: verifies the call, runs the handler, answers as the [Hook API](hook-api.md#the-answer) says. Every other request goes to `app`. `serve` installs it |
| `verify_hook_assertion(assertion, body, *, kind, jwks, issuer, plugin_identifier)` | The checks of [Verification](hook-api.md#verification), outside the runner. Returns `VerifiedHook(claims, request)` or raises `HookAssertionRejected` |
| `HookAssertionRejected` | `.reason` names the failed check |

An install or upgrade handler is `async def handler(request: HookRequest, epicstaff: OrgClient)
-> None`: `request` is the verified body, and `epicstaff` the client for `request.org.id`, acting
as the plugin alone. An organization removed handler is `async def handler(request: HookRequest)
-> None`: the organization has no service account any more, so it gets no client, and deletes
only the plugin's own data. Return to succeed; raise to fail, with the exception's first line as
the error. Handlers for one organization run one at a time, whatever their kind. An upgrade
handler's `request.previous_version` is the version the organization was last brought to
(`null` only when it never finished an install); compare it with `epicstaff_plugin.versions`.
[Write an install hook](../how-to/install-hook.md),
[Write an upgrade hook](../how-to/upgrade-hook.md) and
[Delete your data when an organization leaves](../how-to/org-removed-hook.md) walk through one
of each.

## `epicstaff_plugin.versions`

The order of plugin versions: SemVer 2.0 precedence, the rule EpicStaff applies when it decides
whether an uploaded package is newer than the installed one
([Compatibility and versioning](compatibility-and-versioning.md)).

| Name | What it does |
|---|---|
| `is_newer(candidate, than) -> bool` | Whether `candidate` is a newer version than `than`. A version that differs only in build metadata is not newer |
| `compare_versions(left, right) -> int` | -1 when `left` is older, 0 when it is the same version, 1 when it is newer |
| `version_key(version)` | A sort key: `sorted(versions, key=version_key)` puts them oldest first. Compare keys only with each other |

Each raises `ValueError` for anything that is not a SemVer 2.0 version (the manifest's
`version` rule). Major, minor and patch compare as numbers, so `0.10.0` is newer than `0.9.9`; a
pre-release is older than its release (`1.0.0-rc.1 < 1.0.0`); build metadata is ignored, so
`0.7.0+2` is the same version as `0.7.0`.

```python
from epicstaff_plugin.versions import is_newer


@hook_registry.on_upgrade
async def upgrade(request: HookRequest, epicstaff: OrgClient) -> None:
    if request.previous_version is None or is_newer("0.7.0", request.previous_version):
        await set_up_what_0_7_0_needs(epicstaff)
```

The same functions are in `epicstaff_plugin.contracts.versions`.

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
| `contracts.runtime.DATABASE_URL_ENVIRONMENT_VARIABLE`, `DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE`, `HTTPS_PROXY_ENVIRONMENT_VARIABLE`, `PROXY_ENVIRONMENT_VARIABLES`, `NO_PROXY_ENVIRONMENT_VARIABLES`, `LOOPBACK_NO_PROXY_HOSTS` | The names of the environment variables the node sets for the database and the egress proxy ([reference](runtime.md#environment)) |
| `contracts.hook_api.HookRequest`, `HookAssertionClaims`, `HookResponse`, `HOOK_PATHS` | Hook calls ([reference](hook-api.md)) |
| `contracts.hook_api.KEYLESS_HOOK_KINDS` | The hook kinds whose organization holds no service-account key when they run (`org_removed`): their handler gets no client ([reference](hook-api.md#the-call)) |
| `contracts.hook_api.ORG_REMOVED_RETRY_DELAYS_SECONDS`, `ORG_REMOVED_RETRY_WINDOW_SECONDS`, `org_removed_retry_delay(attempt)` | When EpicStaff tries a failed organization removed hook again: 60, 300 and 1800 seconds after attempts 1–3, then every 3600, for 7 days from the first attempt ([reference](hook-api.md#what-happens-when-an-organizations-data-is-deleted)) |
| `contracts.hook_api.UPGRADE_RETRY_DELAYS_SECONDS`, `upgrade_retry_delay(failures_in_series)` | When EpicStaff tries a failed upgrade hook again: 60 seconds after the first failure in a row, 300 after the second, then not by itself (`None`) ([reference](hook-api.md#what-happens-on-an-upgrade)) |
| `contracts.versions.version_key`, `compare_versions`, `is_newer` | The order of versions, also as `epicstaff_plugin.versions` ([above](#epicstaff_pluginversions)) |
| `contracts.service_account_api.ServiceAccountInfo`, `PluginPerson`, `PeopleLookupRequest`, `PeopleLookupResponse` | What EpicStaff's `/api/plugin-runtime/` endpoints answer ([reference](service-account-api.md)) |

Each model refuses unknown fields, so whoever builds a document cannot misspell one. Read a
document from a newer EpicStaff leniently with `Model.model_validate_json(raw, extra="ignore")`,
as the SDK does.
