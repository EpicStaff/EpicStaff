# Enable the plugin platform

Plugins add pages to EpicStaff. A SuperAdmin uploads a plugin package, reviews it, approves it and
grants it to organizations; members of those organizations then find the plugin in the left bar.
Each plugin is served from its own host name, `<identifier>.<PLUGINS_BASE_DOMAIN>` (for example
`weather.plugins.example.com`), and shown inside EpicStaff in a frame. This page is what an
operator sets up for that. How to build and sign a package is in [the plugin docs](../README.md).

A plugin is a web page, which nginx serves, and may have a Python backend. Backends run on the
**plugin node**, the `es_plugins` container, each as a process and Unix user of its own; nginx's
**gateway** asks Django about every request to `<identifier>.<PLUGINS_BASE_DOMAIN>/api/` before
passing it on. A deployment whose plugins are all frontend-only does not need the node.

## Before you start

- **HTTPS.** The plugin platform runs only over HTTPS. Plain http is allowed only for local
  development on `*.localhost` names, and EpicStaff refuses to start otherwise (see
  [What stops at start-up](#what-stops-at-start-up)).
- **A domain name.** EpicStaff must be reached by a domain name; a deployment reached by an IP
  address cannot use plugins.
- **EpicStaff and the plugins on one site.** EpicStaff's host and the plugin hosts must share a
  registrable domain: `epicstaff.example.com` with `plugins.example.com` works,
  `epicstaff.example.com` with `plugins.example.net` does not. A plugin shown in EpicStaff's frame
  signs its user in through EpicStaff inside that frame, and the browser sends EpicStaff's login
  cookie (`SameSite=Lax`) there only when the frame and the page around it are the same site.
  Otherwise sign-in works only when the plugin is opened in a tab of its own.
- **EpicStaff outside the plugin domain.** EpicStaff's own host must not be the base domain or a
  name under it (`plugins.example.com`, `app.plugins.example.com`); Django refuses to start then
  (`plugins.E010`).
- **One wildcard DNS record**, `*.plugins.example.com`, pointing at the same address as EpicStaff.
- **One wildcard TLS certificate** for `*.plugins.example.com`. Let's Encrypt issues wildcard
  certificates only through the DNS-01 challenge.
- **A base domain you will keep.** Every plugin's address is built from it. Browsers keep each
  plugin's data under its address, and plugins may register their address with outside services
  (for example as an OAuth callback). Changing the base domain later breaks all of that.
- **For plugin backends:** a range of Unix user ids that nothing else on the Docker host uses (see
  `PLUGINS_NODE_UID_RANGE` below), and the architecture of the host (`x86_64` or `aarch64`) among
  the ones a plugin was packed for.

## 1. DNS

Add one record, `*.plugins.example.com`, with the same target as EpicStaff's own name (an `A`/`AAAA`
record, or a `CNAME` to EpicStaff's name). No record per plugin is needed.

## 2. Certificate

Put the wildcard certificate and its key next to EpicStaff's own (see [SSL](../../setup/ssl.md)):

```
src/nginx/certs/plugins-fullchain.pem   # certificate for *.plugins.example.com
src/nginx/certs/plugins-privkey.pem     # its private key
```

With `NGINX_SSL_MODE="on"` and plugins on, nginx does not start without these two files. After a
renewal, reload nginx: `docker compose exec epicstaff-nginx nginx -s reload`.

A self-signed wildcard certificate for testing, from the repo root (replace the domain):

```bash
docker run --rm -v "$(pwd)/src/nginx/certs:/certs" -w /certs alpine \
  sh -c "apk add openssl && openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout plugins-privkey.pem -out plugins-fullchain.pem \
    -subj '/CN=*.plugins.example.com' -addext 'subjectAltName=DNS:*.plugins.example.com'"
```

## 3. Settings

Set these in `src/.env`. `src/env.yaml` holds the full descriptions and the defaults. Every
variable must be present in `src/.env`, also with plugins off: `docker compose` refuses to start
without one. `make env-update` adds the ones your file lacks, with their defaults.

**The platform**

| Variable | Default | What to set |
|---|---|---|
| `PLUGINS_ENABLED` | `false` | `true` turns on the plugin API in Django, the plugin hosts, the gateway and the upload route in nginx, and the plugin pages in the UI. The same spellings as `CHAT_ENABLED` are accepted. |
| `PLUGINS_BASE_DOMAIN` | `plugins.invalid` (production), `plugins.epicstaff.localhost` (development) | The parent of every plugin host, in lower case: `plugins.example.com`. The production default is a placeholder that EpicStaff refuses with plugins on. |
| `PLUGINS_TRUSTED_SIGNING_KEYS` | `none` | The publishers you trust, comma-separated `<name>:<minisign public key>`. Packages signed by one of these keys are shown as Trusted; see [trust and signing](../explanation/trust-and-signing.md). |
| `PLUGINS_MAX_PACKAGE_MB` | `300` | The largest package an upload may carry, in MiB (1 MiB = 1,048,576 bytes). Django applies it to the package; nginx accepts a request body one MiB larger, for the multipart framing. Before nginx reads any of an upload, it asks Django (without the body) whether the caller is a logged-in SuperAdmin, and refuses everyone else with 401 or 403, so nobody else can make EpicStaff store a large body. A proxy in front of EpicStaff must allow that size too. |
| `PLUGINS_STORAGE_BUCKET` | `epicstaff-plugins` | The bucket in EpicStaff's storage that keeps uploaded packages. Created on the first upload. |
| `PLUGINS_GATEWAY_SECRET` | `none` | A random value of at least 32 characters, made of letters, digits and `. _ ~ + / = -`: `openssl rand -hex 32`. nginx sends it with every gateway check, and Django answers a check without it with 404. Required with plugins on. |
| `DJANGO_FRONTEND_BASE_URL` | already set | The exact origin people open EpicStaff at, such as `https://epicstaff.example.com`: scheme, host and port only, no path (a trailing `/` is allowed). Only this origin may frame a plugin page, so any other value (the development default `http://localhost:4200`, a different port) leaves every plugin page blank. It is also the issuer of the signed context plugin backends verify. |
| `DJANGO_REFRESH_COOKIE_SECURE` | already set | `true` on HTTPS. It also chooses the name and path of EpicStaff's login cookie (see [Sign-in and EpicStaff's login cookie](#sign-in-and-epicstaffs-login-cookie)). |
| `DJANGO_ALLOWED_HOSTS` | already set | Only if you restrict it (the default is `*`): add `.plugins.example.com`, because each plugin host fetches its configuration from Django under its own host name, and keep `localhost`, the host name of nginx's gateway checks and of the plugin node's requests. |
| `DJANGO_SGI_WORKERS` | `1` | **At least `2`** once plugins have real traffic. Every request to a plugin's `/api/` asks Django first (the gateway check), and each Django worker is replaced after `DJANGO_SGI_MAX_REQUESTS` requests. With one worker, every replacement pauses all of EpicStaff and every plugin for a few seconds, and plugin traffic makes replacements frequent. With two or more, the others keep answering while one is replaced. Each worker adds Django's memory and its database connections (see `DJANGO_DB_POOL_MAX_SIZE`). |

**The plugin node**

| Variable | Default | What to set |
|---|---|---|
| `COMPOSE_PROFILES` | `none` (production) | Add `plugins` (for example `plugins` or `chat,plugins`) to start the `es_plugins` container. |
| `PLUGINS_NODE_KEY` | `none` | A random value of at least 32 characters: `openssl rand -hex 32`. The node authenticates to Django with it; Django stores only its hash and takes a new value at its next start. Required with plugins on. |
| `PLUGINS_NODE_NAME` | `node-1` | The node's name, shown on each plugin's Runtime tab. |
| `PLUGINS_NODE_UID_RANGE` | `20000-20999` | The Unix user ids the node runs plugin backends as, one per plugin: `<start>-<end>`, with 10000 < start ≤ end < 60000 and at least 10 ids. **Nothing else on the Docker host may use these ids**: process limits count per user id across the whole host, not per container. Two nodes on one host need ranges that do not overlap. |
| `PLUGINS_INTERNAL_API_URL` | `http://epicstaff-api:8081/api/` | Leave as is. How the node and the plugin backends reach EpicStaff's API: nginx's internal listener, on a network only they share. |
| `PLUGINS_NETWORK_SUBNET` | `10.235.0.0/24` | The fixed IPv4 subnet (CIDR) of that network, `plugins-network`. nginx refuses every request from it on EpicStaff's own site and on the plugin hosts, and serves its internal listener only to it (see [How plugin backends are kept apart](#how-plugin-backends-are-kept-apart)). Needed also with plugins off: the network is created whenever nginx starts. It must not overlap any other Docker network on the host or any network the host routes to (a VPN, the office LAN); Docker refuses an overlapping one and `docker compose up` stops with `Pool overlaps with other one on this address space`. To change it, `docker compose down` (it removes the networks, not the volumes), set the new value, then `up -d`. |
| `ES_PLUGINS_CPUS` | `2` | CPUs for every plugin backend together. |
| `ES_PLUGINS_MEMORY` | `4g` | Memory for every plugin backend together. Keep it above the sum of the plugins' memory limits, or the kernel chooses which process to kill instead of the node. |
| `ES_PLUGINS_DISK_MB_PER_PLUGIN` | `2048` | Disk, in MiB, that each plugin backend's own files (its HOME and TMPDIR) may take, the same for every plugin. See [Disk](#disk). |
| `ES_PLUGINS_FILES_PER_PLUGIN` | `100000` | Files, directories and links that each plugin backend's HOME may hold, the same for every plugin. See [Disk](#disk). |

**Platform maximums** (what a plugin may ask for; a package asking for more is refused at upload)

| Variable | Default | Meaning |
|---|---|---|
| `PLUGINS_MAX_PROCESS_MEMORY_MB` | `1024` | Largest memory limit of one plugin backend. |
| `PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE` | `120` | Highest rate a public path may declare, counted per client address. |
| `PLUGINS_MAX_REQUEST_BODY_MB` | `20` | Largest request body nginx accepts on a plugin host (a whole number of MiB above 0); a public path's own cap may not be larger. |
| `PLUGINS_MAX_DB_CONNECTIONS`, `PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS`, `PLUGINS_MAX_REQUESTS_PER_MINUTE` | `20`, `60`, `600` | Accepted and checked against manifests, not enforced yet. |

[Limits](../reference/limits.md) says which limits this version enforces and how.

## 4. Apply

`restart` does not re-read `src/.env`; recreate the containers that read the settings, and start
the node:

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d django_app epicstaff-nginx frontend
docker compose -f docker-compose.yaml --env-file ./.env --profile plugins up -d es_plugins
```

With `plugins` in `COMPOSE_PROFILES`, a plain `docker compose up -d` starts the node too.

The frontend writes its `config.json` when it starts. If you mount your own `config.json` instead,
add `"isPluginsEnabled": true` to it.

When the node is up, `docker compose ps es_plugins` shows it `healthy`: its agent writes a
heartbeat every few seconds, and the container's health check fails when the heartbeat is more
than 30 s old. Approving a plugin with a backend fails with `no_plugin_node` until Django has
registered the node, which it does at start-up from `PLUGINS_NODE_NAME` and `PLUGINS_NODE_KEY`.

## What stops at start-up

Wrong values stop a container with a message instead of serving a broken plugin page.

**django_app** (Django system checks, only with plugins on):

| Check | Fails when |
|---|---|
| `plugins.E001` | `DJANGO_REFRESH_COOKIE_SECURE` is false and `PLUGINS_BASE_DOMAIN` does not end in `.localhost`. Over plain http a plugin page could plant cookies that EpicStaff would trust. |
| `plugins.E002` | `PLUGINS_BASE_DOMAIN` is not a lower-case DNS name, or ends in `.invalid`. |
| `plugins.E003` | `DJANGO_FRONTEND_BASE_URL` is not an `http://` or `https://` origin with a host name (letters, digits and hyphens, not an IP address) and an optional port (anything after the host and port but a trailing `/` counts as not an origin), or is `http://` on a host that does not end in `.localhost`. |
| `plugins.E004` | An entry of `PLUGINS_TRUSTED_SIGNING_KEYS` is not `<name>:<public key>`, or two entries have the same name or the same public key. |
| `plugins.E005` | `DJANGO_CORS_ALLOWED_ORIGINS` lists a plugin host (`PLUGINS_BASE_DOMAIN` or a name under it). Cross-origin calls to EpicStaff carry the person's login, so a plugin page must never be allowed one. |
| `plugins.E006` | `PLUGINS_GATEWAY_SECRET` is `none` or shorter than 32 characters. |
| `plugins.E007` | `PLUGINS_NODE_KEY` is `none` or shorter than 32 characters. |
| `plugins.E008` | `PLUGINS_NODE_UID_RANGE` is not `<start>-<end>` with 10000 < start ≤ end < 60000 and at least 10 ids. |
| `plugins.E009` | A `PLUGINS_MAX_*` value is not a positive whole number. |
| `plugins.E010` | The host of `DJANGO_FRONTEND_BASE_URL` is `PLUGINS_BASE_DOMAIN` or a name under it. A plugin's address could then be EpicStaff's own, and EpicStaff would refuse its own pages as a plugin's. |

**epicstaff-nginx** exits with an `ERROR:` line when `PLUGINS_ENABLED` is not a boolean, and, with
plugins on, when `PLUGINS_BASE_DOMAIN` is not a lower-case DNS name of two or more labels,
`DJANGO_FRONTEND_BASE_URL` is not `http(s)://<host>[:<port>]` with at most a trailing `/` (a
path, query or fragment is refused, as Django's `plugins.E003` does), `PLUGINS_MAX_PACKAGE_MB` or
`PLUGINS_MAX_REQUEST_BODY_MB` is not a whole number of MiB above 0, or `PLUGINS_GATEWAY_SECRET` is
`none`, shorter than 32 characters or holds another character than the ones above (the value is
never printed), or `PLUGINS_NETWORK_SUBNET` is not an IPv4 CIDR such as `10.235.0.0/24`. With
plugins off nginx does not read the plugin values at all.

**es_plugins** exits when `PLUGINS_NODE_UID_RANGE` is not a valid range, `PLUGINS_NODE_KEY` is
`none` or shorter than 32 characters, or `ES_PLUGINS_DISK_MB_PER_PLUGIN` or
`ES_PLUGINS_FILES_PER_PLUGIN` is not a whole number above 0, and when a port of its range (20001–20999) cannot be bound
at start-up; Docker then restarts it, and its log names the variable or the port.

**frontend** exits when `PLUGINS_ENABLED` is not a boolean.

## Check it

After a SuperAdmin has approved a plugin with a backend (the sample `weather`, version 0.3.0,
answers its public path `GET /api/ping`, and `GET /api/whoami` for a signed-in person), check
nginx's plugin routes and the gateway from any machine that reaches EpicStaff:

```bash
EPICSTAFF_URL=https://epicstaff.example.com PLUGINS_BASE_DOMAIN=plugins.example.com \
PLUGIN_IDENTIFIER=weather PLUGINS_MAX_PACKAGE_MB=300 bash src/nginx/tests/plugins_smoke.sh
```

It prints one `ok` or `not ok` line per check. Extra arguments are passed to every curl call, for
example `--cacert ca.pem` for a certificate of your own CA, or `--insecure`. With
`SMOKE_ADMIN_TOKEN` set to a SuperAdmin's access token it also streams a 51 MiB upload to Django;
with `GATEWAY_LOAD_SECONDS=30` it also measures the gateway check's latency under load (every
plugin backend request waits for it).

Then check sign-in, as a person who may use the plugin in one organization (with Weather, any
role but Viewer). Use an account made for the check: the script signs it in and out, also when
it stops early. It sends up to four login requests, and EpicStaff allows five a minute per
address and account, so leave a minute between two runs.

```bash
SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGIN=weather \
SMOKE_EMAIL=smoke@example.com SMOKE_PASSWORD='…' SMOKE_ORG_ID=3 \
bash src/nginx/tests/login_smoke.sh
```

It checks EpicStaff's login cookie (its name and attributes, and that a duplicated or old-named
cookie is no session), that login takes JSON only, the redirects of the sign-in, the token
exchange from the plugin's address, the plugin's `/api/whoami` with that token, that the token
opens none of EpicStaff's API, and that neither a plugin page nor a page with `Origin: null` (a
sandboxed frame) can call it. Extra arguments go to curl as above; with
`SMOKE_LOAD_SECONDS=30` it also times `/api/whoami` with the token.

With plugins off it checks what still applies: the login cookie's name and attributes, that a
duplicated or old-named cookie is no session, that login takes JSON only, that
`/api/plugins/available/` and the authorize endpoint answer 404, and the logout. It notices plugins are off by itself (both endpoints 404),
or set `SMOKE_PLUGINS_OFF=1`, which needs no `SMOKE_ORG_ID`:

```bash
SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGIN=weather \
SMOKE_EMAIL=smoke@example.com SMOKE_PASSWORD='…' SMOKE_PLUGINS_OFF=1 \
bash src/nginx/tests/login_smoke.sh
```

The repository has two labs that need nothing but Docker: `bash src/nginx/tests/gateway/run.sh`
checks the gateway's header and path rules and its overhead under load, and
`bash src/es_plugins/lab/run.sh` runs the node exactly as compose defines it with probe plugins
and checks what a plugin process can and cannot do (it downloads wheels, so it needs network
access). If you change the nginx templates, `bash src/nginx/tests/check_templates.sh`
renders them with every combination of settings, runs `nginx -t` on each and checks that only
Django receives or sets cookies (needs Docker and `openssl`).

## Sign-in and EpicStaff's login cookie

People sign in to a plugin with their EpicStaff login: the plugin's page asks EpicStaff and gets a
token for that plugin alone, valid for 15 minutes and renewed while the page is open. The token
reaches nginx's gateway and nothing else; no EpicStaff credential ever reaches the plugin.
Nothing needs configuring for it, but EpicStaff's login cookie changed with it, plugins on or off.

| `DJANGO_REFRESH_COOKIE_SECURE` | Cookie | Path | Attributes |
|---|---|---|---|
| `true` (HTTPS) | `__Host-auth.refresh` | `/` | `HttpOnly; Secure; SameSite=Lax`, no `Domain` |
| `false` (plain http, development only) | `auth.refresh` | `/api/auth/` | `HttpOnly; SameSite=Lax`, no `Domain` |

- **Everyone is signed out once.** On HTTPS, EpicStaff no longer reads the `auth.refresh` cookie
  of earlier versions, so after the upgrade every person signs in again, once. Plain http
  deployments keep their sessions.
- **Only EpicStaff's own host can set the cookie.** Browsers accept a `__Host-` cookie only from
  the exact host, over HTTPS, without a `Domain`, so a plugin host cannot set it for EpicStaff. A
  request that carries the cookie more than once counts as signed out: a cookie planted by
  another site can sign someone out, never in as somebody else.
- **Only Django gets and sets cookies.** With `Path=/` the browser sends the cookie with every
  request to EpicStaff's host. nginx removes the `Cookie` header from every request it sends to
  anything but Django (the web app's files, webhooks, realtime voice, the audit trail and the chat
  service, which may run elsewhere, at `CHAT_UPSTREAM_URL`), and drops any `Set-Cookie` they
  answer with, so none of them can replace EpicStaff's login cookie. None of them uses cookies.
- **A plugin page cannot use EpicStaff's API.** Django refuses every request whose `Origin` is a
  plugin host (`403 plugin_origin_refused`), except the token exchange, which is the one
  cross-origin call it allows, and never with credentials.
- **A plugin token outlives a logout** by up to 15 minutes, as EpicStaff's own access tokens do.

## How plugin backends are kept apart

The node container runs with a read-only root file system, `no-new-privileges`, and only the
`SETUID`, `SETGID` and `CHOWN` capabilities, for its launcher process. Each plugin backend runs
as its own user id from `PLUGINS_NODE_UID_RANGE`, without any capability, with at most 64
processes and 1024 open files, in its own session. Its secret settings reach it only in a file
that only its own user id can read.

A plugin **cannot** read another plugin's settings, environment, code, data or Python
environment, signal or trace its processes, or reach the node's launcher. A plugin **can** see
the node's process list, with every process's command line, user id and memory, the ports
the others listen on, and the identifiers of the installed plugins; it can open a connection to
another plugin's port, where that plugin refuses any request without a context signed by
EpicStaff. That is why no secret is ever put on a command line.

A plugin cannot take another plugin's port either, nor one a plugin installed later will get.
When it starts, the node binds every port of its range (20001–20999) and keeps them all; it hands
each plugin's process the listening socket of that plugin's port, and `epicstaff-plugin` serves
on it. No plugin can bind a port of the range at all.

The node is on an internal Docker network only, `plugins-network`, which it shares with nothing
but nginx: plugin backends cannot reach the internet or EpicStaff's other services in this
version. nginx refuses every request from the network's subnet (`PLUGINS_NETWORK_SUBNET`) on
EpicStaff's own site and on the plugin hosts, so a plugin backend cannot use EpicStaff or another
plugin the way a browser does. All it can reach is EpicStaff's API through nginx's internal
listener (`epicstaff-api:8081`), which serves only that subnet and refuses the API's login,
administration and gateway routes. A memory limit is checked every 2 s against the memory every
process of the plugin's user id holds, so a plugin can overshoot it briefly; the container's
`ES_PLUGINS_MEMORY` is the hard limit for all of them. `/dev/shm` is read-only, so plugin
backends have no POSIX shared memory (see [Limits](../reference/limits.md)). Disk is capped per
plugin too; see [Disk](#disk).

## Disk

Every plugin backend writes its own files to its HOME and TMPDIR on the `es_plugins_data` volume,
next to the node's copies of the plugins' code and Python environments. A Docker volume has no
size limit of its own: on a default install it is a directory on the host's file system, the one
EpicStaff's database and Docker's own data live on, so a plugin that filled it would stop them
too. The node caps each plugin and keeps a floor of free space, but for a hard boundary give the
volume a file system of its own.

**Give `es_plugins_data` its own file system.** Mount a dedicated disk, partition or file system
image on the host, for example at `/srv/es-plugins`, and bind the volume to it in a
`src/docker-compose.override.yaml`:

```yaml
volumes:
  es_plugins_data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /srv/es-plugins
```

Pass it with the main file (`docker compose -f docker-compose.yaml -f
docker-compose.override.yaml --env-file ./.env ...`). Do this before the node first starts. To
move an existing node, stop es_plugins, copy the volume's content into the new file system with
its ownership kept (`docker run --rm -v <project>_es_plugins_data:/from -v /srv/es-plugins:/to
alpine cp -a /from/. /to/`; `docker volume ls` shows the volume's full name), remove the old
volume, and start the node again. Size the file system for at least
`ES_PLUGINS_DISK_MB_PER_PLUGIN` × the number of plugin backends, plus a few hundred MB per plugin
for its code and Python environment, plus the 2 GiB install reserve below.

**The cap per plugin.** Every 30 s the node measures each running plugin's HOME (TMPDIR is inside
it): the blocks its files take, so a sparse file counts what it really uses, and its files,
directories and links, each one inode. Deleted files that the plugin's processes still hold open
count too. Symlinks are counted as links and never followed. A plugin above
`ES_PLUGINS_DISK_MB_PER_PLUGIN` or `ES_PLUGINS_FILES_PER_PLUGIN` is stopped at once and marked
failed, without the restarts a crash gets: it would only fill its HOME again. A plugin whose use
the node cannot measure completely (it made a directory unreadable to itself, nested directories
more than 128 deep, or stopped the node from seeing a process's open files) is treated the same.
Between two measurements a plugin can write past its cap, by its write rate × 30 s.

**The floor for the whole volume.** Below 2 GiB or 100,000 free inodes the node starts no
download and builds no Python environment: a plugin that needs one fails with the free space in
its error, and the plugins already installed keep running. A package is at most
`PLUGINS_MAX_PACKAGE_MB` and its environment a few times that, so installing never takes the
volume to the floor. Below 512 MiB or 20,000 free inodes, the node stops the running plugin that
uses the most disk (or the most files) and marks it failed; it stops another only if the free
space keeps falling (by 64 MiB or 1,000 inodes more). 512 MiB leaves the database and Docker room
to write while you free space.

**After a plugin failed for its disk**, make room before restarting it: the files are still
there, and the node would stop it again at its next measurement. The plugin's files are in
`data/<identifier>/` of the volume. To see what takes the space, from the host:

```bash
docker run --rm -v <project>_es_plugins_data:/data:ro alpine du -sh /data/data/<identifier>/*
```

Delete what the plugin does not need (for example its caches) the same way, without `:ro`, then
press Restart on the Runtime tab.

## When a plugin does not run

The Runtime tab of a plugin (SuperAdmin) shows what the node reports: state, health, restarts,
memory, the last error and, for a failed plugin, the end of its log.

| You see | Cause and fix |
|---|---|
| The plugin stays `provisioning`, the node is not online | The node is not running or cannot authenticate: `docker compose ps es_plugins`, `docker compose logs es_plugins`. `PLUGINS_NODE_KEY` must be the same for django_app and es_plugins; recreate django_app after changing it. |
| `<project> <version> has no wheel for this node (its wheels are built for …)` | The package has no wheel of that project for this host's architecture. The publisher packs again for it (`epicstaff-plugin pack --download-wheels`, which by default packs for both `x86_64` and `aarch64`). |
| `failed` after repeated restarts | The backend kept stopping: it was restarted ten times in a row without once staying healthy for a minute in between (the node waits 1 s before the first restart, doubling up to 5 minutes, so this takes at least 13.5 minutes). Read the log on the Runtime tab, fix the cause (often a setting), then press Restart. |
| The backend exits at once with `Address already in use` in its log | It opens a server socket itself instead of serving on the socket the node hands it (`EPICSTAFF_PLUGIN_LISTEN_FD`, which `epicstaff-plugin` uses); every port of the node's range is the node's. The publisher must fix the backend. |
| `port … is still in use by placement …` | The plugin got a port another plugin on the node is just giving up (EpicStaff moved them). The node tries again every 30 s; it passes once the other is stopped. |
| `port … is not one of this node's ports` | The node and django_app disagree about the port range: they are of different versions. Run the same version of both. |
| `bin/python is not a symlink; a wheel may have replaced it` | A wheel in the package installs a program of its own over the plugin's Python. The node refuses to install the package; the publisher must remove that wheel. |
| `uses … MB of disk, more than its limit of … MB` or `has … files, more than its limit of … files` | The plugin's own files reached `ES_PLUGINS_DISK_MB_PER_PLUGIN` or `ES_PLUGINS_FILES_PER_PLUGIN`. Free space in its HOME, or raise the cap for every plugin, then press Restart (see [Disk](#disk)). |
| `its disk use cannot be measured: …` | The plugin hid part of its files from the node (an unreadable directory, more than 128 nested directories, a process that does not let the node see its open files). The publisher must fix the backend. |
| `the node's disk has only … MB free, and installing needs 2048 MB` | The `es_plugins_data` volume is below its install reserve. Free space on it (or give it more), then press Restart. |
| `the node's disk is almost full (…), and this plugin uses the most of it (…)` | The volume fell below its floor and this plugin used the most of it. Free space, then press Restart; consider a file system of its own for the volume. |
| Restarts with `more than its memory limit` | The plugin needs more memory than its effective limit: remove a lower override on the Limits tab, or ask the publisher to request more (up to `PLUGINS_MAX_PROCESS_MEMORY_MB`). |
| Sign-in works when the plugin is opened in its own tab, not inside EpicStaff | EpicStaff and the plugin hosts are not on the same registrable domain, so the browser does not send EpicStaff's login cookie inside the frame (see [Before you start](#before-you-start)). |
| A person sees "You do not have access to <plugin> in this organization" | Their role in that organization gives no View on the plugin, the plugin is not granted to the organization (or the grant is suspended), or they are not a member of it. A SuperAdmin is no exception: only a membership counts. |
| A plugin page reports `insecure_context` | The plugin host is served over plain http on a name that does not end in `.localhost`; browsers allow sign-in only in a secure context. Use HTTPS. |

A backend's output is also in the node's log, each line prefixed with `[<identifier>]`
(`docker compose logs es_plugins`), and in `/var/lib/es_plugins/logs/<identifier>/` inside the
`es_plugins_data` volume (10 MB, three files).

## Local development

| Variable | Value |
|---|---|
| `PLUGINS_ENABLED` | `true` |
| `PLUGINS_BASE_DOMAIN` | `plugins.epicstaff.localhost` |
| `NGINX_SERVER_NAME` | `epicstaff.localhost` |
| `NGINX_SSL_MODE` | `off` |
| `DJANGO_FRONTEND_BASE_URL` | `http://epicstaff.localhost` |
| `DJANGO_REFRESH_COOKIE_SECURE` | `false` |
| `PLUGINS_GATEWAY_SECRET`, `PLUGINS_NODE_KEY` | each the output of `openssl rand -hex 32` |
| `COMPOSE_PROFILES` | add `plugins` |

Open EpicStaff at `http://epicstaff.localhost`, not `http://localhost`: a plugin at
`http://weather.plugins.epicstaff.localhost` must be a subdomain of EpicStaff's own name. Chrome and
Firefox send every `*.localhost` name to your machine without DNS; other tools may need one
`/etc/hosts` line per name. Plain http works only on `*.localhost` names, which browsers treat as a
secure context; sign-in refuses any other http page. Safari treats `*.localhost` names
differently, so test Safari against a real domain over HTTPS, or against `*.test` names in
`/etc/hosts` over HTTPS with a certificate of a local CA your browser trusts.

## Where plugin data lives

| What | Where |
|---|---|
| Uploaded packages | The `PLUGINS_STORAGE_BUCKET` bucket in EpicStaff's storage |
| Approved plugins' web files, as served | The `plugin_spa` Docker volume: django_app writes it, epicstaff-nginx reads it |
| Plugins, approvals, grants, settings (secrets encrypted) and limits | EpicStaff's database |
| Plugin backends' own files, their installed code and Python environments, their logs | The `es_plugins_data` Docker volume |

Back up the `plugin_spa` and `es_plugins_data` volumes with the bucket and the database. The node
rebuilds code and Python environments from the packages when they are missing; plugins' own files
in the volume it cannot rebuild.

## Turning plugins off

Set `PLUGINS_ENABLED=false`, recreate django_app, epicstaff-nginx and frontend, and stop the node
(`docker compose stop es_plugins`, and remove `plugins` from `COMPOSE_PROFILES`). Plugin host
names then reach EpicStaff's own pages, the plugin API answers 404 and the plugins leave the left
bar. Nothing is deleted: packages, approvals, grants, settings, published files and the node's
volume stay, and come back when you turn the platform on again.

## Behind another proxy or load balancer

If TLS ends in front of EpicStaff, route `*.plugins.example.com` to EpicStaff's nginx as well, keep
the `Host` and `Origin` headers as the browser sent them (Django refuses plugin pages by their
`Origin`, and binds each sign-in to it), pass the response header `X-EpicStaff-Gateway-Deny` on
unchanged (it marks the gateway's own refusals, by which a plugin's page tells "sign in again"
from the plugin's own errors), allow request bodies of `PLUGINS_MAX_PACKAGE_MB` plus one MiB on
`/api/admin/plugins/packages/` and of `PLUGINS_MAX_REQUEST_BODY_MB` on the plugin hosts, let
WebSocket upgrades and long-lived streams (server-sent events) through to the plugin hosts, and
put the wildcard certificate on that proxy. Then set `NGINX_SSL_MODE=off` and
`DJANGO_REFRESH_COOKIE_SECURE=true`.

nginx then sees the proxy's address as every client's. The rate limit of a public path is counted
per client address, so all clients share one count, and one busy client can use up a public
path's rate for everyone. To count each client, have the proxy send the client's address in
`X-Forwarded-For` and enable nginx's real-IP module for it, in a configuration file of your own at
http level in the `epicstaff-nginx` container (under `/etc/nginx/conf.d/`):

```nginx
set_real_ip_from 192.0.2.10;    # your proxy's address, and nothing wider
real_ip_header X-Forwarded-For;
```

Trust only your proxy's own address. Never list a range that contains `PLUGINS_NETWORK_SUBNET`
(such as `10.0.0.0/8` or `0.0.0.0/0`): a plugin backend could then send any address in
`X-Forwarded-For`, pass nginx's refusal of the plugins network, and spread its requests over
made-up addresses.

The `epicstaff-nginx` service sets the `net.ipv4.tcp_tw_reuse` sysctl for its own container (no
extra privileges). It lets nginx reuse closed connections' local ports, so a busy proxied route
(a plugin backend gets a new connection per request) does not run out of them and start
answering 502.

## Upgrading to this version

This version adds required variables: `PLUGINS_GATEWAY_SECRET`, `PLUGINS_NODE_NAME`,
`PLUGINS_NODE_KEY`, `PLUGINS_NODE_UID_RANGE`, `PLUGINS_INTERNAL_API_URL`,
`PLUGINS_NETWORK_SUBNET`, `PLUGINS_MAX_PROCESS_MEMORY_MB`, `PLUGINS_MAX_DB_CONNECTIONS`,
`PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS`, `PLUGINS_MAX_REQUESTS_PER_MINUTE`,
`PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE`, `PLUGINS_MAX_REQUEST_BODY_MB`, `ES_PLUGINS_CPUS`,
`ES_PLUGINS_MEMORY`, `ES_PLUGINS_DISK_MB_PER_PLUGIN` and `ES_PLUGINS_FILES_PER_PLUGIN`. `docker compose` refuses to start until `src/.env` has them; `make
env-update` adds them with their defaults, which keep plugins off. Set the two secrets before
turning plugins on, and check that the default `PLUGINS_NETWORK_SUBNET` overlaps none of your
networks: it applies with plugins off too.

On HTTPS deployments everyone is signed out once after this upgrade, plugins on or off: EpicStaff's
login cookie is now `__Host-auth.refresh` (see
[Sign-in and EpicStaff's login cookie](#sign-in-and-epicstaffs-login-cookie)).
