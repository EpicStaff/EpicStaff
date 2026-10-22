# Runtime: how a plugin backend runs

A plugin's backend runs as its own process on the deployment's plugin node, under a Unix user
of its own, on a port of its own. This page is what that process can rely on: how it is
started, its environment, its runtime file, its file system, its network, and what other plugins
on the same node can and cannot see of it. The [Python SDK](python-sdk.md) reads all of it for you.

## How the backend is started

The node builds a virtual environment for each version of the plugin with the Python the
manifest names (`backend.python`, CPython 3.12 or 3.13), offline, from the package. The
environment is made without pip and holds none. The node installs the backend with the pip that
ships with the plugin's interpreter, run from outside the environment, so nothing in your package
can replace the installer:

```
pip install --isolated --prefix <venv> --ignore-installed --no-deps --no-index --find-links backend/wheels --require-hashes --only-binary=:all: -r backend/requirements.lock
```

Scripts that wheels put in the environment's `bin/` start the environment's own Python. A build
that fails leaves no environment behind. The node puts `backend/src` on the environment's import path, and starts:

```
<venv>/bin/python -I -m epicstaff_plugin.serve
```

`epicstaff_plugin.serve` reads the runtime file, imports the ASGI app the manifest's
`backend.entrypoint` names, and serves it with uvicorn: one worker, no `Server` header, proxy
headers ignored, lifespan events on (an app that does not handle them fails to start). Importing
the entrypoint module registers your [hook](hook-api.md) handlers. In front of your app it puts
three things you cannot turn off, in this order:

1. `GET /_epicstaff/health` answers `200 {"status":"ok"}`. The node calls it every 15 s;
   three failures in a row restart the process. The node reads only the status line, and the
   whole exchange, connecting included, has one deadline of 3 s.
2. `POST` on the hook paths (`/_epicstaff/hooks/…`) runs your hook handler, once the call's
   [hook assertion](hook-api.md#verification) verifies; these calls never reach your app.
3. Every other request needs a valid [gateway context](gateway-context.md); without one it is
   answered `401 {"code":"context_invalid"}` and never reaches your app.

**The platform owns the port.** The node binds the plugin's port itself and keeps it bound while
the plugin restarts, so no other process on the node can take it in between. It passes the
listening socket to the process as file descriptor 3 (`EPICSTAFF_PLUGIN_LISTEN_FD`), and
`serve` serves on that socket and never binds one. Your backend cannot open listening sockets
of its own: the node refuses every `bind()` of an IPv4 or IPv6 socket by a plugin process, TCP
and UDP alike, with `Operation not permitted` (`EPERM`), on `PORT` and on any other port.
Outgoing connections are not affected, within the [connection limits](limits.md#connections).
`serve` refuses to start when the descriptor is not a listening TCP socket. Without `EPICSTAFF_PLUGIN_LISTEN_FD`, on your own machine, `serve` binds
`0.0.0.0:$PORT` itself.

**The node watches every plugin's sockets**, once a second. A `listen()` on a socket the
plugin did not bind still takes a port, and so does a UDP socket that is connected and never
sends. So the node stops a plugin whose user has a TCP socket in LISTEN on any port, or holds
more than 1,280 network sockets, TCP and UDP together. TCP connections the plugin accepted on its
own port do not count. The plugin's Runtime tab then gives the reason,
"it listened on TCP port … of its own; …" or "it held … network sockets, more than the 1280 a
plugin may; …", and the plugin stays stopped until a SuperAdmin restarts it.

`io_uring` is not available: `io_uring_setup`, `io_uring_enter` and `io_uring_register` answer
`EPERM`, as do the System V IPC calls `shmget`, `msgget` and `semget`, and every system call
made through a 32-bit ABI. So do `unshare`, `setns`, `keyctl`, `add_key`, `request_key`, `bpf`,
`perf_event_open` and `userfaultfd`, and `clone` with any namespace flag. `clone3` answers
`ENOSYS`, and glibc then falls back to `clone`, so threads and child processes work.

So your lock must pin `uvicorn` and `epicstaff-plugin` (upload refuses a lock without them), and
your app must be an ASGI app: FastAPI, Starlette, Litestar, Django's ASGI handler and so on.
uvicorn is installed as your lock pins it; WebSockets need a WebSocket library in the lock
(`websockets` or `wsproto`), as uvicorn's own documentation describes.

The process is restarted when its settings change, when a SuperAdmin restarts it or changes its
limits, and when it exits or fails its health check (after 1 s, then backing off to 5 minutes).
After 10 restarts in a row without staying healthy for a minute in between, the plugin is marked
failed and stays stopped until a SuperAdmin restarts it; the Runtime tab of the plugin shows the
last lines of its log.

## Environment

The process gets exactly these variables; nothing is inherited from the node.

| Variable | Value |
|---|---|
| `PORT` | The plugin's port, stable for the plugin's life. For information: the node has bound it already |
| `EPICSTAFF_PLUGIN_LISTEN_FD` | `3`: the listening socket the node opened on `PORT`, which `serve` serves on |
| `USER`, `LOGNAME` | The plugin's id |
| `HOME` | `/var/lib/es_plugins/data/<id>`, the plugin's own writable directory |
| `TMPDIR` | `/var/lib/es_plugins/data/<id>/tmp` |
| `PATH` | `<venv>/bin:/usr/local/bin:/usr/bin:/bin` |
| `LANG` | `C.UTF-8` |
| `PYTHONUNBUFFERED` | `1` |
| `EPICSTAFF_PLUGIN_IDENTIFIER` | The plugin's id |
| `EPICSTAFF_PLUGIN_VERSION` | The running version |
| `EPICSTAFF_PLUGIN_ENTRYPOINT` | The manifest's `backend.entrypoint` |
| `EPICSTAFF_PLUGIN_RUNTIME_FILE` | `/run/es_plugins/<id>/runtime.json` |
| `EPICSTAFF_API_URL` | EpicStaff's API as the plugin reaches it, the runtime file's `epicstaff_api_url` |
| `EPICSTAFF_PUBLIC_URL` | EpicStaff's address in people's browsers, the runtime file's `epicstaff_public_url` |
| `EPICSTAFF_PLUGIN_PUBLIC_URL` | The plugin's own public address, the runtime file's `public_url` |
| `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY`, `http_proxy` | `http://<id>:<password>@plugins_egress:3128`: the egress proxy, with the plugin's own credentials ([Call the internet from your backend](../how-to/outbound-hosts.md)) |
| `NO_PROXY`, `no_proxy` | The host of `epicstaff_api_url`, then `localhost,127.0.0.1,::1`: reached directly, not through the proxy |
| `DATABASE_URL` | With a `database` section only: `postgresql://<id_>_app:<password>@<host>:<port>/plugin_<id_>?application_name=<id>`, the plugin's own database as its app role ([Plugin database](database.md)) |
| `EPICSTAFF_PLUGIN_DB_CONNECTIONS` | With a `database` section only: the app role's connection limit |

Your settings' secrets are only in the runtime file, never in the environment or on the command
line. The platform's own credentials for your database and for the egress proxy are in the
environment: `DATABASE_URL` and the proxy variables. Both the file and the environment are
readable only by your plugin's user. Don't hand your environment to code you don't trust: a
child process gets all of it unless you start it with a smaller one.

## Runtime file

A JSON document at `EPICSTAFF_PLUGIN_RUNTIME_FILE`, readable only by the plugin's user (mode
0400). Its model is `epicstaff_plugin.contracts.runtime.RuntimeFile`.

```json
{
  "format": 1,
  "plugin": { "identifier": "weather", "version": "0.2.0" },
  "issuer": "https://epicstaff.example.com",
  "public_url": "https://weather.plugins.example.com",
  "epicstaff_public_url": "https://epicstaff.example.com",
  "epicstaff_api_url": "http://epicstaff-api:8081/api/",
  "settings": { "units": "metric" },
  "secret_settings": { "forecast_api_token": "…" },
  "service_accounts": { "3": { "key": "esp-…", "org_name": "Acme", "grant_state": "active" } },
  "jwks": { "keys": [ { "kty": "OKP", "crv": "Ed25519", "x": "…", "kid": "…", "alg": "EdDSA", "use": "sig" } ] },
  "public_paths": [ { "path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0 } ]
}
```

| Field | Meaning |
|---|---|
| `format` | `1` |
| `plugin` | The plugin's id and the running version |
| `issuer` | EpicStaff's public origin, the `iss` of every gateway context |
| `public_url` | The plugin's own address. Build every external callback address (OAuth redirect URIs and the like) from it; operators keep it stable |
| `epicstaff_public_url` | EpicStaff's address in people's browsers |
| `epicstaff_api_url` | EpicStaff's API from inside the node. Only `/api/` is reachable there, without `/api/auth/` and `/api/admin/` |
| `settings` | Every non-secret setting: its stored value, else its default. An optional setting with neither is left out |
| `secret_settings` | The secret settings that are set, in clear text. Unset ones are left out |
| `service_accounts` | The plugin's [service account](#service-accounts) in each organization it is granted to, keyed by the organization id as text |
| `jwks` | The keys gateway contexts are signed with: the current one and any retired in the last 24 h |
| `public_paths` | The manifest's public paths, as the gateway applies them |

Settings are deployment-wide: one value per plugin, set by a SuperAdmin on the plugin's Settings
tab. Saving them restarts the process, so read them whenever you need them or once at start-up;
both see the current values.

The node rewrites the file atomically (a rename) when EpicStaff's signing keys change and when
the plugin's service accounts change, without restarting the process. `RuntimeConfig` in the SDK
notices the change and reads the file again. A newer EpicStaff may add fields; read the file
with the SDK, or ignore fields you do not know.

### Service accounts

```json
"service_accounts": { "3": { "key": "esp-…", "org_name": "Acme", "grant_state": "active" } }
```

There is one entry per organization whose grant holds a key: `granting` while the install hook
runs, then `active`, and `upgrading` while the organization's upgrade hook runs after an upgrade.
Do background work for an organization only while it is `active`. A grant whose install or
upgrade hook failed holds none, nor does an organization the plugin is not granted to.

| Field | Meaning |
|---|---|
| `key` | `esp-` and 43 more characters: `Authorization: PluginKey <key>` on calls to EpicStaff's API in that organization |
| `org_name` | The organization's name |
| `grant_state` | The grant's state, as text: a newer EpicStaff may add states |

EpicStaff keeps only a hash of each key and issues new ones every time the node fetches the
runtime file: at every start or restart of the process, and whenever the plugin is granted to
another organization or a grant changes state. The key before the current one keeps working for
10 minutes, so calls in flight during a rewrite still succeed. Read the key from the current file
for every call (`RuntimeConfig.service_account(org_id)`; the SDK's
[client](../how-to/call-epicstaff-from-the-backend.md) does), and never store or log it.

A key works only on `epicstaff_api_url`, from the plugin network; EpicStaff refuses it on its
public address. The keys of a [development backend](#a-development-backend) work only on the
development API listener instead.

## File system and identity

| Path | Access |
|---|---|
| `HOME` and `TMPDIR` | Read and write, yours alone. Keep your files here. Both count towards the operator's per-plugin disk and file caps ([limits](limits.md)); a plugin over a cap is stopped and marked failed. The node must be able to measure everything here: don't make directories unreadable to yourself and don't call `prctl(PR_SET_DUMPABLE, 0)` — a plugin it cannot measure is treated as over the cap |
| `/tmp` | **Not writable.** Use `TMPDIR`; Python's `tempfile` does so already |
| `/dev/shm` | **Not writable**, so there is no POSIX shared memory: `multiprocessing` locks, queues and pools (and `ProcessPoolExecutor`) need its semaphores and fail. Use threads, asyncio or subprocesses |
| Your code and virtual environment | Read-only |
| Everything else | Read-only, or not readable at all |

The plugin's user has a number but no entry in `/etc/passwd`: `pwd.getpwuid(os.getuid())` raises
`KeyError`. Use `os.environ["USER"]` or `getpass.getuser()`, which reads it, and
`os.path.expanduser("~")`, which reads `HOME`.

Write logs to standard output and standard error. The node keeps the last 30 MB of them per
plugin, and shows the last 200 lines on the Runtime tab when the plugin fails.

## Network

The backend reaches EpicStaff's API at `epicstaff_api_url`, its own database when it has one,
and the egress proxy, and nothing else. The backend's process has no route to the internet but
through the proxy,
which lets through HTTPS on port 443 to the hosts in the manifest's `outbound_hosts`, and
outside names do not resolve
([Call the internet from your backend](../how-to/outbound-hosts.md)). Code that runs in
EpicStaff's sandbox through flows is not the backend's process: it has the sandbox's own network
access, which `outbound_hosts` do not bound.

## Other plugins on the same node

Several plugins share a node. Each runs as a different user, so a plugin **cannot**:

- read another plugin's environment, runtime file, code, virtual environment or files;
- send signals to or trace another plugin's processes;
- reach the node's own supervisor.

But every plugin on the node **can**:

- list every process, with its user number, memory use and **full command line**;
- see which ports are listening, and which plugins are installed;
- connect to every other plugin's port, within its own [connection limits](limits.md#connections).

Hence two rules:

- **Never put a secret in a command line**, your own or a child process's: every plugin on the
  node can read it. That includes `DATABASE_URL` and the proxy URL (`psql "$DATABASE_URL"` puts
  the password on one). Pass secrets in environment variables of the child or in files under
  `HOME`.
- **Trust a request only through its gateway context or hook assertion.** Another plugin can
  call your port directly, but it can forge neither: `epicstaff_plugin.serve` refuses every
  request without a valid one, which is why it cannot be turned off.

## Limits

The node caps the memory of all processes of the plugin's user together, and runs them at the
CPU priority the plugin's limits give. Above the cap it stops every process of the plugin and
restarts it. The cap counts the resident memory of those processes: memory a plugin holds in a
memory file (`memfd_create`) or a tmpfs is not counted, though the node's own memory limit still
bounds it. [Limits](limits.md) gives the details, including by how much the memory cap can be
overshot.

## A development backend

On a deployment in plugin development mode, which runs only on a developer's own machine, a
SuperAdmin can point an installed plugin at a backend that `epicstaff-plugin dev` runs from the
plugin's source ([Local development](../how-to/local-development.md#develop-the-backend-on-your-machine),
[`epicstaff-plugin dev`](cli.md#epicstaff-plugin-dev)). EpicStaff's gateway then sends the
plugin's backend requests there, with the same checks and the same gateway contexts. What
differs from the plugin node:

| | On the plugin node | A development backend |
|---|---|---|
| Started by | The node: `python -I -m epicstaff_plugin.serve` | You: `epicstaff-plugin dev`, which composes the same app |
| Listens on | The socket the node hands it on `PORT` | `--host` and `--port`, which it binds itself (`127.0.0.1:8001` by default); EpicStaff reaches it at `host.docker.internal:<port>` |
| Requests | Every request to the plugin's `/api/` | The same, while the backend port is set on the plugin's Development tab |
| Hooks | Run here | Still run on the installed version on the node, which keeps running |
| Runtime file | `/run/es_plugins/<id>/runtime.json`, rewritten by the node when keys or grants change | The development runtime file a SuperAdmin downloaded. It is never rewritten: download it again, to the same path, after the plugin is granted to another organization or suspended in one |
| Service-account keys | Node keys, replaced at every start | Development keys, one per organization the plugin holds a key in. They work only on the development API listener, and only while development mode is on. "Stop development", a new download, and suspending the plugin in an organization revoke them; resuming issues none, so download the file again |
| `epicstaff_api_url` | `http://epicstaff-api:8081/api/`, on the plugins network | `http://127.0.0.1:<PLUGINS_DEV_API_PORT>/api/` (port 8082 by default), the development API listener on your machine's loopback |
| Database | The plugin's own database (`DATABASE_URL`) | None, or the local database you pass with `--database-url` |
| Outbound requests | Only to the declared hosts, through the egress proxy | Your machine's network, with no allow-list and no proxy variables from EpicStaff |
| User, files, limits | A Unix user, `HOME` and `TMPDIR` of its own, and the plugin's limits | Your user and your files; no limit applies |
| Settings, public paths, access, user permissions | The installed version's | Still the installed version's: your source's changes to them take effect only in a new version |

The development runtime file is a runtime file like the node's, of the same format, holding the
plugin's secret settings and keys that act for it in every organization it is granted to. Keep
it outside your plugin's source, readable by you only: `epicstaff-plugin dev` refuses one inside
the source, and `pack`, `validate` and EpicStaff's upload refuse a package that holds one.
