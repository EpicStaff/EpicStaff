# Enable the plugin platform

Plugins add pages to EpicStaff. A SuperAdmin uploads a plugin package, reviews it, approves it and
grants it to organizations; members of those organizations then find the plugin in the left bar.
Each plugin is served from its own host name, `<identifier>.<PLUGINS_BASE_DOMAIN>` (for example
`weather.plugins.example.com`), and shown inside EpicStaff in a frame. This page is what an
operator sets up for that. How to build and sign a package is in [the plugin docs](../README.md).

A plugin is a web page, which nginx serves, and may have a Python backend. Backends run on the
**plugin node**, the `es_plugins` container, each as a process and Unix user of its own; nginx's
**gateway** asks Django about every request to `<identifier>.<PLUGINS_BASE_DOMAIN>/api/` before
passing it on. A backend calls EpicStaff's API as the plugin's **service account** in each
organization the plugin is granted to, within the access its package declares (see
[Service accounts](#service-accounts)). A backend may also keep its data in a database of its own
on `plugins_db` (see [Plugin databases](#plugin-databases)), and reach the internet hosts its
package declares through the egress proxy, `plugins_egress` (see
[Outbound access](#outbound-access)). A deployment whose plugins are all frontend-only does not
need the node.

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
| `PLUGINS_GRACE_PERIOD_DAYS` | `30` | Days a suspended or uninstalled plugin keeps its data before it is deleted. Resuming or reinstalling within this time restores everything. A whole number from 1 to 3650; EpicStaff refuses to start with plugins on otherwise (`plugins.E011`). Each suspension records its deadline when it happens, so a changed value applies only to later suspensions: set it before the first suspension. A suspended plugin's process keeps running, for the other organizations it is granted to; suspending stops it only in the one organization (see [Suspending a plugin in an organization](#suspending-a-plugin-in-an-organization)). |
| `PLUGINS_STORAGE_BUCKET` | `epicstaff-plugins` | The bucket in EpicStaff's storage that keeps uploaded packages. Created on the first upload. |
| `PLUGINS_GATEWAY_SECRET` | `none` | A random value of at least 32 characters, made of letters, digits and `. _ ~ + / = -`: `openssl rand -hex 32`. nginx sends it with every gateway check and with every request that comes through its internal API listener. Django answers a check without it with 404, and accepts a plugin's service-account key or the node's key only on a request that carries it. Required with plugins on. |
| `DJANGO_FRONTEND_BASE_URL` | already set | The exact origin people open EpicStaff at, such as `https://epicstaff.example.com`: scheme, host and port only, no path (a trailing `/` is allowed). Only this origin may frame a plugin page, so any other value (the development default `http://localhost:4200`, a different port) leaves every plugin page blank. It is also the issuer of the signed context plugin backends verify. |
| `DJANGO_REFRESH_COOKIE_SECURE` | already set | `true` on HTTPS. It also chooses the name and path of EpicStaff's login cookie (see [Sign-in and EpicStaff's login cookie](#sign-in-and-epicstaffs-login-cookie)). |
| `DJANGO_ALLOWED_HOSTS` | already set | Only if you restrict it (the default is `*`): add `.plugins.example.com`, because each plugin host fetches its configuration from Django under its own host name, and keep `localhost`, the host name of nginx's gateway checks and of the plugin node's requests. |
| `DJANGO_SGI_WORKERS` | `1` | **At least `2`** once plugins have real traffic. Every request to a plugin's `/api/` asks Django first (the gateway check), and each Django worker is replaced after `DJANGO_SGI_MAX_REQUESTS` requests. With one worker, every replacement pauses all of EpicStaff and every plugin for a few seconds, and plugin traffic makes replacements frequent. With two or more, the others keep answering while one is replaced. Each worker adds Django's memory and its database connections (see `DJANGO_DB_POOL_MAX_SIZE`). |

**The plugin node**

| Variable | Default | What to set |
|---|---|---|
| `COMPOSE_PROFILES` | `none` (production) | Add `plugins` (for example `plugins` or `chat,plugins`) to start the `es_plugins`, `plugins_db` and `plugins_egress` containers. |
| `PLUGINS_NODE_KEY` | `none` | A random value of at least 32 characters: `openssl rand -hex 32`. The node authenticates to Django with it; Django stores only its hash and takes a new value at its next start. Required with plugins on. |
| `PLUGINS_NODE_NAME` | `node-1` | The node's name, shown on each plugin's Runtime tab. |
| `PLUGINS_NODE_UID_RANGE` | `20000-20999` | The Unix user ids the node runs plugin backends as, one per plugin: `<start>-<end>`, with 10000 < start ≤ end < 60000 and at least 10 ids. **Nothing else on the Docker host may use these ids**: process limits count per user id across the whole host, not per container. Two nodes on one host need ranges that do not overlap. |
| `PLUGINS_INTERNAL_API_URL` | `http://epicstaff-api:8081/api/` | Leave as is. How the node and the plugin backends reach EpicStaff's API: nginx's internal listener, on a network only they share. |
| `PLUGINS_NETWORK_SUBNET` | `10.235.0.0/24` | The fixed IPv4 subnet (CIDR) of that network, `plugins-network`. nginx refuses every request from it on EpicStaff's own site and on the plugin hosts, and serves its internal listener only to it (see [How plugin backends are kept apart](#how-plugin-backends-are-kept-apart)). Needed also with plugins off: the network is created whenever nginx starts. It must not overlap any other Docker network on the host or any network the host routes to (a VPN, the office LAN); Docker refuses an overlapping one and `docker compose up` stops with `Pool overlaps with other one on this address space`. To change it, `docker compose down` (it removes the networks, not the volumes), set the new value, then `up -d`. |
| `ES_PLUGINS_CPUS` | `2` | CPUs for every plugin backend together. |
| `ES_PLUGINS_MEMORY` | `4g` | Memory for every plugin backend together. Keep it above the sum of the plugins' memory limits, or the kernel chooses which process to kill instead of the node. |
| `ES_PLUGINS_DISK_MB_PER_PLUGIN` | `2048` | Disk, in MiB, that each plugin backend's own files (its HOME and TMPDIR) may take, the same for every plugin. See [Disk](#disk). |
| `ES_PLUGINS_FILES_PER_PLUGIN` | `100000` | Files, directories and links that each plugin backend's HOME may hold, the same for every plugin. See [Disk](#disk). |

**Plugin databases** (see [Plugin databases](#plugin-databases))

| Variable | Default | What to set |
|---|---|---|
| `PLUGINS_DB_SUPERUSER_PASSWORD` | `none` | `openssl rand -hex 32`. The `postgres` superuser's password, used once, when `plugins_db` first initializes its volume. The superuser works only over the container's own socket, never over the network. |
| `PLUGINS_DB_ADMIN_PASSWORD` | `none` | `openssl rand -hex 32`. The password of `plugins_admin`, the plugin node's login on `plugins_db`, which creates every plugin's database and roles. `plugins_db` sets it at its first start and es_plugins logs in with it, so both must have the same value. It can read every plugin's data: keep it like a root password. |
| `PLUGINS_DB_BACKUP_PASSWORD` | `none` | `openssl rand -hex 32`. The password of `plugins_backup`, the login the plugin node backs plugin databases up with before an upgrade (see [Backups](#backups)). `plugins_db` sets it at its first start and es_plugins logs in with it, so both must have the same value. It can read every plugin's data: keep it like a root password. |
| `PLUGINS_DB_MAX_CONNECTIONS` | `200` | `plugins_db`'s connection limit: at least the number of plugin backends times `PLUGINS_MAX_DB_CONNECTIONS`, plus 10. 5 of these are kept for the plugin node (see [Plugin databases](#plugin-databases)). |

The three passwords must each be at least 32 characters, and `none` is refused, whenever the
`plugins` profile runs. `plugins_db` reads them only when it initializes an empty volume: changing
a value in `src/.env` later changes nothing in the database (see
[Plugin databases](#plugin-databases) for how to change one).

**Platform maximums** (what a plugin may ask for; a package asking for more is refused at upload)

| Variable | Default | Meaning |
|---|---|---|
| `PLUGINS_MAX_PROCESS_MEMORY_MB` | `1024` | Largest memory limit of one plugin backend. |
| `PLUGINS_MAX_PUBLIC_REQUESTS_PER_MINUTE` | `120` | Highest rate a public path may declare, counted per client address. |
| `PLUGINS_MAX_REQUEST_BODY_MB` | `20` | Largest request body nginx accepts on a plugin host (a whole number of MiB above 0); a public path's own cap may not be larger. |
| `PLUGINS_MAX_REQUESTS_PER_MINUTE` | `600` | Highest rate of calls to EpicStaff's API a plugin may ask for. It is counted per service account, so per organization the plugin is granted to; a call over the rate gets `429` with `Retry-After`. |
| `PLUGINS_MAX_DB_CONNECTIONS`, `PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS` | `20`, `60` | Highest connection limit and statement timeout a plugin's database may ask for. The node sets both on the plugin's database role and restores them within a minute if the plugin changes them. The node also lets no plugin backend have more than `PLUGINS_MAX_DB_CONNECTIONS` connections open to `plugins_db` at once, logged in or not. |

[Limits](../reference/limits.md) says which limits this version enforces and how.

## 4. Apply

`restart` does not re-read `src/.env`; recreate the containers that read the settings, and start
the node:

```bash
cd src
docker compose -f docker-compose.yaml --env-file ./.env up -d django_app epicstaff-nginx frontend
docker compose -f docker-compose.yaml --env-file ./.env --profile plugins up -d plugins_db plugins_egress es_plugins
```

With `plugins` in `COMPOSE_PROFILES`, a plain `docker compose up -d` starts these three too.

`docker compose ps plugins_db` shows it `healthy` once its first start has created its roles.
`docker compose logs plugins_egress` shows `egress firewall installed`, then `waiting for the plugin
node's policy files` until the node has started, and then Squid starting; it turns `healthy` once
Squid accepts connections.

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
| `plugins.E011` | `PLUGINS_GRACE_PERIOD_DAYS` is not a whole number from 1 to 3650. |

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
`ES_PLUGINS_FILES_PER_PLUGIN` is not a whole number above 0, `PLUGINS_DB_ADMIN_PASSWORD` or
`PLUGINS_DB_BACKUP_PASSWORD` is `none` or shorter than 32 characters, the egress policy volume
cannot be written, a port of its range (20001–20999) cannot be bound, or the per-plugin
connection limits or the refusal of `bind()` cannot be set at start-up (`The per-plugin connection
limits could not be set`: the container lacks `NET_ADMIN` or `BPF`, or the Docker host gives it no
cgroup v2, which needs Linux 5.8 or later and Docker's default cgroup setup); Docker then restarts
it, and its log names the variable, the port or the step.

**plugins_db**, when it initializes an empty volume, refuses a password variable that is `none`
or shorter than 32 characters. Its log names the variables, never their values, and it removes the
cluster it had begun, so every later start initializes again and refuses again until the values
are fixed. Once it has initialized, it no longer reads them.

**plugins_egress** exits when IPv6 is on in its container (the compose file's sysctls turn it
off), when it cannot install or verify its firewall, or when Squid would start with more than the
`SETUID` and `SETGID` capabilities (`refusing to start`: the container lacks `SETPCAP`; see
[Outbound access](#outbound-access)).

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

Then check a plugin backend's service account, on the machine that runs the stack, once the
plugin is granted to an organization. It needs three people: a member of that organization whose
role gives View on the plugin, a member whose role gives none (with Weather, a Viewer), and
someone who is not a member. Pass their user ids:

```bash
SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 \
SMOKE_PERSON_ID=11 SMOKE_OUTSIDER_ID=12 SMOKE_NO_VIEW_ID=13 \
bash src/nginx/tests/service_account_smoke.sh
```

It reads the plugin's key for that organization from its runtime file in the `es_plugins`
container (as root, without printing it) and calls EpicStaff's API with it from a throwaway curl
container on `plugins-network`, the way the backend does. It checks that the key works through
nginx's internal listener and is refused on EpicStaff's public address, that the people endpoint
answers for the member with View and not for the outsider, that the backend may act on behalf of
the member with View and not of the one without, and that a person-only endpoint (the flow
assistant's) refuses the key. Extra arguments go to the curl call to `SMOKE_BASE_URL`, as above.

Then check suspending and resuming, on the machine that runs the stack, with a SuperAdmin, an Org
Admin of the organization and a flow of that organization that uses something the plugin owns
(with Weather, the flow its install hook creates). The script leaves the grant active, also when a
check fails:

```bash
SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 \
SMOKE_PLUGIN_FLOW_ID=41 SMOKE_SUPERADMIN_EMAIL=root@example.com SMOKE_SUPERADMIN_PASSWORD='…' \
SMOKE_ORG_ADMIN_EMAIL=ada@example.com SMOKE_ORG_ADMIN_PASSWORD='…' \
bash src/nginx/tests/suspend_smoke.sh
```

It suspends the grant and checks that the plugin's key for the organization stops working and the
organization leaves the runtime file within 30 seconds, that the Org Admin's run of the flow is
refused with `plugin_suspended`, then resumes and checks that a new key appears and works, the old
one stays refused, and the run starts. It starts one session of the flow and stops it again. Extra
arguments go to curl as above.

Then check outbound access, on the machine that runs the stack, with a plugin that declares an
outbound host (the Weather sample declares `geocoding-api.open-meteo.com`). Pass the plugin's user id,
which its Runtime tab shows:

```bash
PLUGIN_IDENTIFIER=weather PLUGIN_UID=20001 bash src/plugins_egress/smoke/check_egress.sh
```

It asks the egress proxy from inside `es_plugins` as the plugin's own user id, with the proxy URL
the plugin's process got, which it reads the way the plugin could and never prints. It checks that
the declared host is reached; that an undeclared host, IP addresses in several spellings, other
ports and plain http are refused, each with its reason; that wrong or missing credentials get
`407`; that there is no way out around the proxy; that the plugin cannot read the proxy's policy;
the proxy container's IPv6, firewall and capabilities; and that its log names the plugin and holds
no credential. `DECLARED_URL` changes the URL it fetches.

Last, and only on a stack you can lose the plugin on, check deleting. **It deletes the plugin for
good**, so it refuses to run without `--yes`:

```bash
SMOKE_BASE_URL=https://epicstaff.example.com SMOKE_PLUGINS_BASE_DOMAIN=plugins.example.com \
SMOKE_PLUGIN=weather SMOKE_ORG_ID=3 SMOKE_ORG_NAME=Acme \
SMOKE_SUPERADMIN_EMAIL=root@example.com SMOKE_SUPERADMIN_PASSWORD='…' \
bash src/nginx/tests/purge_smoke.sh --yes
```

It deletes the plugin's data in the organization (after a refused wrong phrase) and waits for the
organization removed hook, grants the plugin again, uninstalls and reinstalls it, then deletes it
for good. It checks that nothing of the plugin is left on the node, in `plugins_db` or in the
egress policy, that its host answers 404, and that its activity is kept. Extra arguments after
`--yes` go to curl as above.

The repository has four labs that need nothing but Docker: `bash src/nginx/tests/gateway/run.sh`
checks the gateway's header and path rules and its overhead under load;
`bash src/es_plugins/lab/run.sh` runs the node exactly as compose defines it with probe plugins
and checks what a plugin process can and cannot do (it downloads wheels, so it needs network
access); `bash src/plugins_db/lab/run.sh` starts `plugins_db` as compose defines it, runs the
node's database tests against it and checks its roles and grants (it needs the es_plugins and
plugin_sdk venvs, `make uv-sync svc=<service>`); and `bash src/plugins_egress/lab/run.sh` runs the
egress proxy as compose defines it against lab clients, a lab DNS server and a private "victim",
including a forced DNS-rebinding attempt (it needs internet access; `--timings` also measures how
long policy changes take). If you change the nginx templates, `bash src/nginx/tests/check_templates.sh`
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

The node container runs with a read-only root file system and `no-new-privileges`. Its launcher
process has the `SETUID`, `SETGID` and `CHOWN` capabilities and no other. The container also has
`NET_ADMIN`, `BPF` and `SETPCAP` for its entrypoint only: before the launcher starts, the
entrypoint installs the per-plugin connection limits below in the container's network namespace
and the refusal of `bind()` in its cgroup, then starts the launcher with nothing but those three
capabilities left in any capability set, so nothing on the node can change them afterwards. A
shell you open in the container with `docker exec` gets the container's capabilities, `NET_ADMIN`
and `BPF` included; no plugin process does. Each plugin backend runs as its own user id from
`PLUGINS_NODE_UID_RANGE`, without any capability, with at most 64 processes and 256 open files
each, no POSIX message queues and no System V IPC objects (a seccomp filter refuses to make or
open them), in its own session. Its secret settings reach it only in a file that only its own user
id can read; its database URL and its proxy URL, credentials included, are in its environment,
which only its own user id can read too.

A plugin **cannot** read another plugin's settings, environment, code, data or Python
environment, signal or trace its processes, or reach the node's launcher. A plugin **can** see
the node's process list, with every process's command line, user id and memory, the ports
the others listen on, and the identifiers of the installed plugins; it can open a connection to
another plugin's port, where that plugin refuses any request without a context signed by
EpicStaff. That is why no secret is ever put on a command line.

A plugin cannot take another plugin's port either, nor one a plugin installed later will get.
When it starts, the node binds every port of its range (20001–20999) and keeps them all; it hands
each plugin's process the listening socket of that plugin's port, and `epicstaff-plugin` serves
on it. No plugin can bind an inet socket at all: `bind()` answers "Operation not permitted" to
every plugin user id.

Plugin backends and the node share the container's network namespace, and with it its local
ports (21000–65535 for outbound connections). So that one plugin cannot use them up, or the
connection slots of `plugins_db` and the egress proxy, each plugin backend may open at most 200
new TCP connections a second (after a burst of 200), and have at most 512 TCP connections open at
once, `PLUGINS_MAX_DB_CONNECTIONS` of them to `plugins_db` and 64 to the egress proxy. A
connection over a limit is refused at once. The node's own connections are never limited. Two
ways of sharing the namespace remain, which several plugins together could use: UDP sockets
connected without sending (each holds a local port; the descriptor limit bounds one plugin's),
and UNIX sockets in the abstract namespace, which every process in the container can reach.

The node is on two internal Docker networks only: `plugins-network`, which it shares with nothing
but nginx and the egress proxy, and `plugins-db-network`, which it shares with nothing but
`plugins_db`. Plugin backends cannot reach EpicStaff's other services, and reach the internet only
through the egress proxy, to the hosts their package declares (see
[Outbound access](#outbound-access)). nginx refuses every request from the network's subnet (`PLUGINS_NETWORK_SUBNET`) on
EpicStaff's own site and on the plugin hosts, so a plugin backend cannot use EpicStaff or another
plugin the way a browser does. All it can reach is EpicStaff's API through nginx's internal
listener (`epicstaff-api:8081`), which serves only that subnet and refuses the API's login,
administration and gateway routes. There it calls as its service account, with the key of the
organization it acts in (see [Service accounts](#service-accounts)). Every request through the
listener carries `PLUGINS_GATEWAY_SECRET`, which nginx adds and no caller can set, and Django
accepts a plugin's key or the node's key only with it: a key copied out of the node is of no use
from anywhere else. A memory limit is checked every 2 s against the memory every
process of the plugin's user id holds, so a plugin can overshoot it briefly; the container's
`ES_PLUGINS_MEMORY` is the hard limit for all of them. `/dev/shm` is read-only, so plugin
backends have no POSIX shared memory (see [Limits](../reference/limits.md)). Disk is capped per
plugin too; see [Disk](#disk).

## Plugin databases

A plugin whose package declares a database gets one on `plugins_db`, a PostgreSQL server of its
own that only the plugin node reaches (Django never connects to it). When a SuperAdmin approves the
plugin, the node creates the database `plugin_<id>` and three roles, `<id>_owner`, `<id>_app` and
`<id>_job`, where `<id>` is the plugin's identifier with `-` turned into `_`, and runs the
package's migrations. The backend connects as `<id>_app` with the `DATABASE_URL` in its
environment. No role of one plugin can connect to another plugin's database, nor to the server's
own `postgres` and `template1`. What a plugin sees of its database is in
[Plugin database](../reference/database.md).

- **One superuser step.** At its first start, `plugins_db` creates `plugins_admin` and
  `plugins_backup` and closes the maintenance databases to everyone else. The `postgres`
  superuser works only over the container's own socket (`docker compose exec -u postgres plugins_db
  psql`), never over the network; `pg_hba.conf` refuses it there.
- **`plugins_admin` lives only in the plugin node.** It creates every plugin's roles, can read
  every plugin's data and can take over any plugin's roles. Keep `PLUGINS_DB_ADMIN_PASSWORD` like a
  root password. The node never runs a plugin's SQL as `plugins_admin`: migrations run as the
  plugin's owner role, which can log in only while they run.
- **Changing a password.** `plugins_db` reads the password variables only on its first start. To
  change `plugins_admin`'s, set it in the server first, then in `src/.env`, and recreate
  es_plugins:
  ```bash
  docker compose exec -u postgres plugins_db psql -c '\password plugins_admin'
  docker compose up -d es_plugins
  ```
- **Limits.** Each plugin's database role gets its effective connection limit and statement
  timeout (the Limits tab). The node checks them every minute: a changed timeout is restored
  ("Timeout restored at …" on the Runtime tab), and a membership or database privilege changed
  outside EpicStaff stops the plugin ("database permissions changed outside EpicStaff").
- **Sizing.** A connection takes one of `plugins_db`'s slots as soon as it is opened, before it
  logs in, so a role's connection limit alone cannot keep a plugin from filling them. The node
  therefore lets each plugin backend have at most `PLUGINS_MAX_DB_CONNECTIONS` connections open to
  `plugins_db` at once, logged in or not. Set `PLUGINS_DB_MAX_CONNECTIONS` to at least the number
  of plugin backends times `PLUGINS_MAX_DB_CONNECTIONS`, plus 10: then however plugins behave, the
  five slots kept for the plugin node stay free. With less, the plugins together can oversubscribe
  the server: each keeps to its own limit, but their sum can exceed the free slots, and a new
  connection then fails until one closes, the plugin node's included.
- **Disk.** Every plugin database shares the server's disk, and PostgreSQL cannot cap one
  database's size: one plugin's data can fill the volume for all of them. The temporary files of
  each server process are capped at 1 GB (`temp_file_limit`), so one plugin's large sorts cannot
  fill it alone. The Runtime tab shows each plugin's database size; watch the `plugins_pgdata`
  volume, and put it on a file system of its own for a hard limit.
- **No statement text in the log.** Failing statements are never logged with their text:
  `plugins_admin` runs with `log_min_error_statement=panic`.

### Backing up plugin databases

Back up the `plugins_pgdata` volume together with EpicStaff's database, taken at the same moment:
each plugin's database belongs to that plugin's installation in EpicStaff's database. Stop
`es_plugins` and `plugins_db`, copy the volume, and start them again. Restore the volume the same
way. Do not restore a plugin database with `psql` or `pg_restore` as the superuser: a dump holds
SQL the plugin wrote, which would then run with the superuser's rights.

### Leftovers from another EpicStaff database

Restoring one of the two without the other, or resetting EpicStaff's database while
`plugins_pgdata` stays, leaves databases and roles in `plugins_db` that the current installation
did not create. The node refuses to use them, and the Runtime tab shows "plugins_db already has …
that this plugin installation did not create". Either restore the matching pair, or remove the
leftovers over the socket, which deletes that plugin's data:

```bash
docker compose exec -u postgres plugins_db psql -c 'DROP DATABASE "plugin_<id>" WITH (FORCE)' \
  -c 'DROP ROLE "<id>_app", "<id>_job", "<id>_owner"'
```

Then press Restart on the plugin's Runtime tab.

## Outbound access

A plugin backend reaches the internet only through `plugins_egress`, a Squid proxy on
`plugins-network` with a network of its own to the outside (`plugins-egress-network`). The node
gives each backend its proxy URL in `HTTPS_PROXY` (and `https_proxy`, `HTTP_PROXY`, `http_proxy`).
The proxy allows a plugin an HTTPS tunnel (`CONNECT`) to port 443 of the hosts its package declares
in `outbound_hosts`, which the review shows before approval, and nothing else. Writing a backend
for it is in [Call the internet from your backend](../how-to/outbound-hosts.md).

- **One password per plugin.** The node makes a plugin's proxy password when it starts the
  plugin's process and keeps it only in memory and in that process's environment; the proxy gets
  a bcrypt hash of it. The node writes the hashes and the host lists into the `plugin_egress_policy`
  volume, below a directory no plugin's user id can enter, so no plugin reads another's. The
  volume is rebuilt at every start of the node and needs no backup.
- **Changes apply within about 30 s.** A newly started plugin works at once. A host leaving a
  plugin's list, or a plugin stopping for good, ends its access within about 30 s, without a
  restart of the proxy. Suspending a plugin in one organization does not change its outbound
  access: that belongs to the plugin, whose process keeps serving its other organizations.
- **HTTPS on 443 only.** Plain http, other ports, hosts off the list and IP addresses get `403`,
  with the reason in the `X-Squid-Error` header; wrong or missing credentials get `407`. A name
  that resolves to a private, loopback, link-local or multicast address is refused
  (`ERR_PRIVATE_DST`).
- **A firewall behind Squid.** Squid checks the resolved address before it connects, but looks
  the name up again to connect, so a DNS answer that changes in between could reach a private
  address. At start-up the proxy's entrypoint installs a firewall in its own container's network
  namespace that refuses every connection to those ranges. That is the only use of `NET_ADMIN`.
  The entrypoint then takes every capability but `SETUID` and `SETGID`, which Squid needs to
  switch to its own user, out of Squid's bounding set: no Squid or helper process holds
  `NET_ADMIN`, so none can change the firewall. Taking capabilities out of the bounding set needs
  `SETPCAP`, so the container has it too; without it, `setpriv` reports success and changes
  nothing, so the entrypoint checks the result and refuses to start Squid when anything more would
  remain. `CHOWN` lets the entrypoint hand the container's log output to Squid's user.
- **IPv6 is off** in that container (the compose file's sysctls; the entrypoint checks it).
  Squid therefore logs `aclIpParseIpData: IPv6 has not been enabled` and
  `BCP 177 violation. Detected non-functional IPv6 loopback` at start: it ignores the IPv6 lines
  of its private ranges, and no IPv6 connection can leave the container. A host with IPv6
  addresses only cannot be reached.
- **DNS works with Docker's resolver or the host's**, private resolvers included: the firewall
  lets DNS out to any address, and Squid opens tunnels to port 443 only.
- **Logs.** `docker compose logs plugins_egress` has a line per request with `user=<identifier>`,
  the host and port, the address connected to and the refusal reason, and never a credential or a
  header. Squid starts without `-d`: its log is already the container's output, which `-d` would
  print twice.
- **Your own public address.** An approved host that resolves to this deployment's own public
  address reaches services on that address that the internet cannot reach. Review such hosts, or
  block that address with the Docker host's firewall.
- **Under a flood.** Each plugin backend may have at most 64 connections open to the proxy at
  once (see [How plugin backends are kept apart](#how-plugin-backends-are-kept-apart)). Under a
  flood, other requests wait behind it. Once the password-check queue has been overloaded for 3
  minutes, new checks get `407` at once instead of the proxy stopping, and when the host-check
  queue is full, the request is refused with `407`, not `403`.
- **What a host list does not stop.** The proxy does not decrypt tunnels, so a host on a content
  delivery network can be asked, inside TLS, for another site it serves; a `*.` entry allows every
  name below it. Read such hosts in a review as access to more than their name.
- **No upstream proxy.** The proxy connects to the internet directly; an upstream corporate proxy
  is not supported in this version.

## Service accounts

A plugin with a backend gets a service account in each organization a SuperAdmin grants it to.
The backend uses it to call EpicStaff's API: to create the flows, files, secrets or LLM
configurations its features need, to run flows, and to look up the people who use it.

- **It can do only what the package declares.** The manifest lists the access the plugin needs
  (for example `flows: read, create, use`), with a reason for each; the SuperAdmin approves that
  list with the package, and the service account gets exactly that in each organization, never
  more, whatever the roles there. It never gets the administration of EpicStaff: organizations,
  members, roles, API keys, the audit log and chats cannot be declared, and person-only features
  (the flow assistant, notification mail, saved audit filters) refuse it.
- **On behalf of a person.** When the backend acts for someone using the plugin, it names them.
  EpicStaff checks that this person may use the plugin in the organization (an active member
  whose role gives View on it) and records them with the request; it does not check what that
  person may do in EpicStaff, so the plugin's declared access is still the limit.
- **Its keys.** The node writes one key per organization into the plugin's runtime file, which
  only the plugin's own Unix user can read. Django keeps only their hashes. The keys are
  replaced every time the plugin's process (re)starts and whenever the organizations it serves
  change (a new grant, a grant that becomes active or ends, a renamed organization); the
  previous key keeps working for 10 minutes. So **Restart** on the Runtime tab replaces every
  key of the plugin.
- **What it did.** Each organization's Settings → Plugin activity (for people who may read the
  audit log, Org Admins by default) lists the plugins acting there with the access they declared,
  and every change a plugin's service account made: who it acted for, the request and what it
  created. A SuperAdmin sees the same for every organization on the plugin's Activity tab.
- **How fast.** Calls are limited per service account to the plugin's `requests_per_minute`
  (at most `PLUGINS_MAX_REQUESTS_PER_MINUTE`).

### Install hooks

A plugin may run an **install hook** when it is granted to an organization, to set itself up
there (the sample `weather` creates its flow and a README in the organization's storage). Its
grant then shows "Installing…" until the hook is done, and only then becomes active; people
cannot open the plugin in that organization until it is.

The node runs the hook once the plugin's process runs, has passed its health check and holds the
organization's key. It asks Django for the job, which answers with a call signed for this one
hook, and makes the call at once on the node's loopback; one hook at a time per plugin. A hook
may take as long as its manifest says (at most 15 minutes for an install hook). If the node
reports no result within that time and two minutes more (it was stopped, or lost its connection
to Django), Django fails the hook itself.

A failed hook leaves the grant **Install failed** with the reason. Fix the cause, then press
**Retry install** on the grants list: the same job runs again, and the plugin is expected to
finish what an earlier attempt began without doing it twice.

| The reason says | Cause and fix |
|---|---|
| The plugin's own message | The plugin's hook failed; its log on the Runtime tab says more. Often the plugin lacks access it did not declare (a publisher fix) or a setting is missing. |
| `timed out after … s` | The hook did not answer within its timeout. Look at the plugin's log. |
| `could not connect: …` | The plugin's process did not take the call. Check its state and log on the Runtime tab. |
| `the connection was lost: …` | The process took the call but closed the connection, or answered with something that is not HTTP, before it answered. Its log says more; a crash in the hook is the usual cause. |
| `the plugin restarted during the hook` | The process was restarted while the hook ran: Restart, a settings change, a crash or its memory limit. Retry. |
| `the plugin stopped during the hook` | The process was stopped while the hook ran (a required setting went missing, the plugin node stopped, or the plugin left the node). Start it again, then retry. |
| `hook assertion rejected: …` | The plugin refused the signed call. Most often the clocks of the Docker host and EpicStaff's server differ by more than 30 s; fix the host's clock (NTP), then retry. |
| `this plugin has no install hook` | The package says it has one, but its backend registers none. The publisher must fix the package. |
| `HTTP …` | The plugin answered with that status and no message of its own. Look at its log. |
| `The plugin node reported no result in time` | The node did not report back: see that it is running and online. |

## Suspending a plugin in an organization

A SuperAdmin can suspend a plugin's grant in one organization, and resume it, in the plugin's Grants table
(see [the lifecycle](../explanation/lifecycle.md) for what each does to the organization). For
the operator:

- **The plugin's process keeps running.** Suspension is per organization: the node removes only that
  organization from the plugin's runtime file, within seconds, and the plugin's backend keeps serving
  its other organizations. Nothing restarts, and no hook is called. To take the plugin out of every organization, suspend each grant.
- **The data is kept for `PLUGINS_GRACE_PERIOD_DAYS`.** Set the variable before the first
  suspension (see [Settings](#3-settings)); a suspension keeps the deadline it was given. When the
  grace period ends, EpicStaff deletes everything the plugin created in that organization, and
  the plugin's organization removed hook deletes the plugin's own data there (see
  [the lifecycle](../explanation/lifecycle.md)). A SuperAdmin can also delete it at once, with
  "Delete data…" in the Grants table.
- **Resume mints new keys.** The organization's keys are revoked at suspension; the next credentials
  refresh of the node, within seconds of the resume, writes a new one.

## Upgrading plugins

A SuperAdmin starts each upgrade. Uploading a newer version of an installed plugin only puts it up
for review: the review shows what the new version may do that the installed one may not (new
access, which the SuperAdmin approves explicitly), its database migrations, and how big the
database's backup will be. "Upgrade to <version>" then runs it:

1. **Preparing.** The plugin keeps running while the node downloads, checks and builds the new
   version next to the installed one. Most failures happen here (a package without wheels for the
   node's platform, not enough disk space), and cost no downtime.
2. **Maintenance.** The plugin goes offline: its pages show "This plugin is being updated", its
   API answers `503`, and runs that use its resources are refused (sessions already running go
   on). The node waits for an organization's hook that is still running, stops the plugin, and
   backs its database up.
3. **Migrations and start.** The node applies the new version's migrations and starts it. Then
   each organization's upgrade hook runs; an organization is offline until its own hook has
   succeeded, and a failing hook is tried again after 1 and 5 minutes.

A backup takes time and room in proportion to the database: the review shows the database's last
size, and the node refuses to stop the plugin when the `es_plugins_data` volume lacks that much
free space above its floor (see [Disk](#disk)). The backups are on that volume (see
[Backups](#backups)).

### When an upgrade fails

The plugin's page shows where the upgrade stopped and the error. EpicStaff never rolls back by
itself.

| Failed while | Options |
|---|---|
| Preparing | The plugin is still running. Fix the cause (disk space, wheels for the node's platform) and Retry, upload a newer version, or Cancel |
| Backing up | Free disk space or fix `plugins_db`, then Retry, or Cancel |
| Running migrations | When the database holds no change of the new version: Cancel. Otherwise: Restore the backup, then Cancel; or upload a newer version that keeps the files already applied; or Retry an error that has passed |
| Starting | Upload a newer version, or Restore, then Cancel |
| An organization's upgrade hook | That organization stays offline. After the automatic retries, Retry on its row, or upload a newer version |

### Backups

- **Before the first migration of an upgrade** the node backs the plugin's database up with
  `pg_dump`, logged in as `plugins_backup`, which reads every table and runs nothing of the
  plugin's. It also backs the database up before each restore, so a restore can be undone.
- **What is kept:** the backups of the three latest upgrades, none older than
  `PLUGINS_GRACE_PERIOD_DAYS`, and every backup an open upgrade or restore still needs. EpicStaff
  decides, and the node deletes only the backups EpicStaff no longer keeps.
- **They hold every organization's data of that plugin**, deleted organizations' included until
  they age out. They are not encrypted: the volume and a directory only the node's agent may
  read (no plugin can) are their protection. Copy them off the host only as carefully as the
  database itself.
- **Where:** `backups/<identifier>/` on the `es_plugins_data` volume, one `.dump` and one
  `.json` each. They go with the plugin when it is deleted.
- **`PLUGINS_DB_BACKUP_PASSWORD`** is read by es_plugins now, as well as by `plugins_db`.
- **EpicStaff restores only during an upgrade that failed**, and only a backup that upgrade took
  (Restore… on the Runtime tab). It replaces the database, after backing up the database as it
  is.
- **A plugin database with large objects cannot be backed up** (`plugins_backup` may not read
  them): such a plugin's upgrades stop at the backup, and can be cancelled. Plugins store binary
  data in `bytea` columns instead.
- **The node carries PostgreSQL 17's `pg_dump` and `pg_restore`**, the major version of
  `plugins_db`. Run the `plugins_db` image this version's compose file names: `pg_dump` refuses
  a server of a newer major version.

### Inspecting an older backup by hand

Restoring an older backup is not offered in EpicStaff. To look at one, first read it without any
database, which runs nothing at all:

```bash
docker compose cp es_plugins:/var/lib/es_plugins/backups/<identifier>/<file>.dump ./
docker compose cp ./<file>.dump plugins_db:/tmp/<file>.dump
docker compose exec plugins_db pg_restore --list /tmp/<file>.dump
docker compose exec plugins_db pg_restore --data-only --table=<table> --file=- /tmp/<file>.dump
```

To query it, restore it **only as the plugin's owner role, into a new database**. Never as
`postgres` or `plugins_admin`: a plugin's functions and triggers in the dump run with the rights of
whoever restores it.

1. Create the database, owned by the owner, and let the owner log in for 10 minutes over the
   socket (the password is asked for, never on a command line):

   ```bash
   docker compose exec -T -u postgres plugins_db psql <<'SQL'
   CREATE DATABASE "inspect_<id>" OWNER "<id>_owner" TEMPLATE template0;
   SELECT format('ALTER ROLE %I LOGIN CONNECTION LIMIT 1 VALID UNTIL %L', '<id>_owner', now() + interval '10 minutes') \gexec
   SQL
   docker compose exec -it -u postgres plugins_db psql -c '\password "<id>_owner"'
   ```

2. Restore as the owner over TCP, giving that password:

   ```bash
   docker compose exec -it plugins_db pg_restore --no-owner --single-transaction --enable-row-security \
     -W -h 127.0.0.1 -U "<id>_owner" -d "inspect_<id>" /tmp/<file>.dump
   ```

   Query it the same way (`psql -W -h 127.0.0.1 -U "<id>_owner" -d "inspect_<id>"`). Tables
   with `FORCE ROW LEVEL SECURITY` show the owner no rows; in this copy, `ALTER TABLE … NO FORCE
   ROW LEVEL SECURITY` lifts that.
3. Close the owner again:

   ```bash
   docker compose exec -u postgres plugins_db psql \
     -c "ALTER ROLE \"<id>_owner\" NOLOGIN PASSWORD NULL CONNECTION LIMIT -1 VALID UNTIL 'infinity'" \
     -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '<id>_owner'"
   ```

   The node closes it within a minute anyway, if you forget.
4. When done, drop the copy and delete the file:

   ```bash
   docker compose exec -u postgres plugins_db psql -c 'DROP DATABASE "inspect_<id>"'
   docker compose exec plugins_db rm /tmp/<file>.dump
   ```

## Uninstalling and deleting plugins

A SuperAdmin uninstalls a plugin, reinstalls it, or deletes it permanently on the plugin's page
(see [the lifecycle](../explanation/lifecycle.md) for what each means for the organizations). For
the operator:

- **Uninstall** stops the plugin's process and suspends the plugin in every organization it is
  granted to. Its data is kept for `PLUGINS_GRACE_PERIOD_DAYS`, and reinstalling within that time
  brings everything back. Until then the process runs only to call the plugin's organization
  removed hook, when an organization's data is being deleted, and it stops between attempts.
- **Deleting permanently**, by a SuperAdmin or when an uninstalled plugin's grace period ends:
  1. the plugin's organization removed hook runs for each organization, so the plugin deletes
     what it keeps there;
  2. then the plugin node stops the plugin, deletes its database and its three roles with every
     one of their connections closed, and removes its code, Python environment, logs, files and
     the System V IPC objects of its user id;
  3. then EpicStaff deletes its frontend and package files.

  The plugin's activity stays, for SuperAdmins.
- **No backup is taken, and the backups the node took before upgrades are deleted with the
  plugin.** Back up the `plugins_pgdata` volume first if you may need the data (see
  [Backing up plugin databases](#backing-up-plugin-databases)).
- **The plugin node must be running** for a deletion to finish. Until the node reports the plugin
  removed, its page shows "Deleting"; an error the node cannot get past shows there too, with
  Retry removal.
- **A database that a different installation created is never deleted.** The deletion stops with
  "plugins_db has … that this plugin installation did not create … and the node will not delete
  them". Resolve it as in
  [Leftovers from another EpicStaff database](#leftovers-from-another-epicstaff-database), then
  press Retry removal.
- **A backup session holds a deletion.** The node ends only the plugin's own sessions; while
  another session, a backup's, is connected to the plugin's database, it tries again every 30
  seconds.
- **Another plugin's database referring to this plugin's roles stops the deletion for good.** The
  deletion stops with "database "plugin_<other>" still refer to this plugin's roles": the plugin
  `<other>` granted access to one of its own tables to this plugin's role, or named it in a
  policy (role names are visible to every plugin). The node also stops `<other>` itself at its
  next check, with "objects in database plugin_<other> refer to role(s) …". Either delete the
  plugin `<other>` first, or remove the references from its database over the socket (this
  changes nothing of `<other>`'s data, only its grants and policies naming those roles):

  ```bash
  docker compose exec -u postgres plugins_db psql -d plugin_<other> \
    -c 'DROP OWNED BY "<id>_app", "<id>_job", "<id>_owner"'
  ```

  Then press Retry removal on this plugin, and Restart on `<other>`. Tell the publisher of
  `<other>`: a new version that grants to another plugin's role would be stopped again.
- **The plugin's user id and port are reused only after the node has removed everything**, so a
  plugin approved later never finds anything of a deleted one.
- **With plugins switched off**, EpicStaff still deletes the plugins' EpicStaff resources when a
  grace period ends. The plugins' own data waits until plugins run again.

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
for its code and Python environment, plus the 2 GiB install reserve below, plus room for the
backups taken before upgrades: up to three per plugin with a database, each about its database's
size or less (see [Backups](#backups)). During an upgrade a plugin's old and new versions are on
the volume together; the old one goes when the upgrade is done.

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
| The backend exits at once with `Operation not permitted` or `Address already in use` in its log | It opens a server socket itself instead of serving on the socket the node hands it (`EPICSTAFF_PLUGIN_LISTEN_FD`, which `epicstaff-plugin` uses); no plugin may bind a socket, and every port of the node's range is the node's. The publisher must fix the backend. |
| `port … is still in use by placement …` | The plugin got a port another plugin on the node is just giving up (EpicStaff moved them). The node tries again every 30 s; it passes once the other is stopped. |
| `port … is not one of this node's ports` | The node and django_app disagree about the port range: they are of different versions. Run the same version of both. |
| `bin/python is not a symlink; a wheel may have replaced it` | A wheel in the package installs a program of its own over the plugin's Python. The node refuses to install the package; the publisher must remove that wheel. |
| `uses … MB of disk, more than its limit of … MB` or `has … files, more than its limit of … files` | The plugin's own files reached `ES_PLUGINS_DISK_MB_PER_PLUGIN` or `ES_PLUGINS_FILES_PER_PLUGIN`. Free space in its HOME, or raise the cap for every plugin, then press Restart (see [Disk](#disk)). |
| `its disk use cannot be measured: …` | The plugin hid part of its files from the node (an unreadable directory, more than 128 nested directories, a process that does not let the node see its open files). The publisher must fix the backend. |
| `the node's disk has only … MB free, and installing needs 2048 MB` | The `es_plugins_data` volume is below its install reserve. Free space on it (or give it more), then press Restart. |
| `the node's disk is almost full (…), and this plugin uses the most of it (…)` | The volume fell below its floor and this plugin used the most of it. Free space, then press Restart; consider a file system of its own for the volume. |
| Database: provisioning, with a connection error as the last error | The node cannot reach or log in to `plugins_db`, and tries again every 30 s. Check `docker compose ps plugins_db`; `PLUGINS_DB_ADMIN_PASSWORD` must be the value `plugins_db` was first started with (see [Plugin databases](#plugin-databases)). |
| "plugins_db already has … that this plugin installation did not create" | A database or roles of that name are left from another EpicStaff database. See [Leftovers from another EpicStaff database](#leftovers-from-another-epicstaff-database). |
| A migration's name with a line and an SQL error, or "… changed after it was applied" | A migration of the package failed and was rolled back, or differs from the one that ran. The publisher fixes the package ([Plugin database](../reference/database.md)). |
| "database permissions changed outside EpicStaff: …" | Someone changed the plugin's roles or its database's grants by hand; the node stopped the plugin. Undo the change, or remove the plugin's database (see above), then press Restart. |
| The backend's outbound requests fail with `403` and `ERR_HOST_NOT_ALLOWED` | The host is not in the package's `outbound_hosts`. The publisher declares it in a new version. |
| The backend's outbound requests time out or fail with `Connection refused` | `plugins_egress` is not running, or still waits for the node's policy files: `docker compose logs plugins_egress`. |
| Restarts with `more than its memory limit` | The plugin needs more memory than its effective limit: remove a lower override on the Limits tab, or ask the publisher to request more (up to `PLUGINS_MAX_PROCESS_MEMORY_MB`). |
| Sign-in works when the plugin is opened in its own tab, not inside EpicStaff | EpicStaff and the plugin hosts are not on the same registrable domain, so the browser does not send EpicStaff's login cookie inside the frame (see [Before you start](#before-you-start)). |
| A person sees "You do not have access to <plugin> in this organization" | Their role in that organization gives no View on the plugin, the plugin is not granted to the organization (or the grant is suspended), or they are not a member of it. A SuperAdmin is no exception: only a membership counts. |
| A plugin page reports `insecure_context` | The plugin host is served over plain http on a name that does not end in `.localhost`; browsers allow sign-in only in a secure context. Use HTTPS. |

A backend's output is also in the node's log, each line prefixed with `[<identifier>]`
(`docker compose logs es_plugins`), and in `/var/lib/es_plugins/logs/<identifier>/` inside the
`es_plugins_data` volume (10 MB, three files). The compose file gives es_plugins, plugins_db and
plugins_egress Docker's `json-file` log driver with a size limit, so one plugin cannot fill the
host's disk through the node's log. That overrides a log driver you set for the Docker daemon;
to send these logs elsewhere, set their `logging:` in a `docker-compose.override.yaml`, with a
size limit of its own.

## Local development

| Variable | Value |
|---|---|
| `PLUGINS_ENABLED` | `true` |
| `PLUGINS_BASE_DOMAIN` | `plugins.epicstaff.localhost` |
| `NGINX_SERVER_NAME` | `epicstaff.localhost` |
| `NGINX_SSL_MODE` | `off` |
| `DJANGO_FRONTEND_BASE_URL` | `http://epicstaff.localhost` |
| `DJANGO_REFRESH_COOKIE_SECURE` | `false` |
| `PLUGINS_GATEWAY_SECRET`, `PLUGINS_NODE_KEY`, `PLUGINS_DB_SUPERUSER_PASSWORD`, `PLUGINS_DB_ADMIN_PASSWORD`, `PLUGINS_DB_BACKUP_PASSWORD` | each the output of `openssl rand -hex 32` |
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
| The backups the node takes before upgrades | `backups/<identifier>/` on the `es_plugins_data` volume, which only the node's agent may read |
| Plugin databases | The `plugins_pgdata` Docker volume (`plugins_db`) |
| The egress proxy's host lists and password hashes | The `plugin_egress_policy` Docker volume, rebuilt at every start of the node |

Back up the `plugin_spa`, `es_plugins_data` and `plugins_pgdata` volumes with the bucket and the
database, `plugins_pgdata` from the same moment as the database (see
[Backing up plugin databases](#backing-up-plugin-databases)). The node rebuilds code and Python
environments from the packages when they are missing; plugins' own files in the volume it cannot
rebuild. `plugin_egress_policy` needs no backup.

## Turning plugins off

Set `PLUGINS_ENABLED=false`, recreate django_app, epicstaff-nginx and frontend, and stop the node,
the plugin databases and the egress proxy (`docker compose stop es_plugins plugins_db
plugins_egress`, and remove `plugins` from `COMPOSE_PROFILES`). Plugin host
names then reach EpicStaff's own pages, the plugin API answers 404, the plugins leave the left
bar and no plugin key is accepted any more (401); people and API keys work as before. Turning
plugins off deletes nothing by itself: packages, approvals, grants, settings, published files, the
node's volume and the plugin databases stay, and come back when you turn the platform on again.
Grace periods keep running, though: when one ends while plugins are off, EpicStaff still deletes
the plugin's EpicStaff resources in that organization, and the plugin's own data waits until
plugins run again.

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
`ES_PLUGINS_MEMORY`, `ES_PLUGINS_DISK_MB_PER_PLUGIN`, `ES_PLUGINS_FILES_PER_PLUGIN`,
`PLUGINS_DB_SUPERUSER_PASSWORD`, `PLUGINS_DB_ADMIN_PASSWORD`, `PLUGINS_DB_BACKUP_PASSWORD` and
`PLUGINS_DB_MAX_CONNECTIONS`. `docker compose` refuses to start until `src/.env` has them; `make
env-update` adds them with their defaults, which keep plugins off. Set the two secrets and the
three database passwords before turning plugins on, and check that the default
`PLUGINS_NETWORK_SUBNET` overlaps none of your networks: it applies with plugins off too.

A `plugins_pgdata` volume initialized by a pre-release build of this version lacks three settings
`plugins_db`'s first start now makes: `plugins_admin` may end plugin roles' sessions
(`pg_signal_backend`), which deleting a plugin and closing its migration runs need, and its failing
statements are never logged with their text. Recreate the volume (this deletes every plugin
database), or run this once:

```bash
docker compose exec -u postgres plugins_db psql \
  -c 'GRANT pg_signal_backend TO plugins_admin' \
  -c 'ALTER ROLE plugins_admin SET log_min_error_statement = panic' \
  -c "ALTER ROLE plugins_admin SET log_statement = 'none'"
```

Either way, then run `docker compose up -d plugins_db`. It recreates the container, so the new
server command (a cap on each session's temporary files) and the new `pg_hba.conf` (which lets
`plugins_backup` log in to plugin databases, for the backups taken before upgrades) apply. `docker
compose restart` keeps the old command, and a reload alone may not see a replaced `pg_hba.conf`
on a Linux host, where a mounted file stays the one the container started with.

es_plugins now needs the `BPF` capability for its entrypoint, which the compose file gives it,
and a Docker host with cgroup v2 (Linux 5.8 or later, Docker's default cgroup setup): recreate it
with `docker compose up -d es_plugins`. It also reads `PLUGINS_DB_BACKUP_PASSWORD`, which must be
the value `plugins_db` was first started with.

On HTTPS deployments everyone is signed out once after this upgrade, plugins on or off: EpicStaff's
login cookie is now `__Host-auth.refresh` (see
[Sign-in and EpicStaff's login cookie](#sign-in-and-epicstaffs-login-cookie)).
