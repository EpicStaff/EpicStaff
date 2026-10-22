# Develop a plugin locally

Run EpicStaff with the plugin platform on your machine and install your plugin there. Then work
on its backend and its page from your source: EpicStaff sends the plugin's requests to the
backend and the development server you run, so a change shows up without packing a new version.
Last, check the plugin in real browsers.

The commands on this page run from the root of an EpicStaff checkout, at the version you develop
against ([Get the tools](../README.md#get-the-tools)), and use the Weather sample,
`plugin-samples/weather/`. For your own plugin, use its directory instead.

## Host names

| What | Address |
|---|---|
| EpicStaff | `http://epicstaff.localhost` |
| A plugin | `http://<id>.plugins.epicstaff.localhost` |

with `DJANGO_FRONTEND_BASE_URL=http://epicstaff.localhost`, `PLUGINS_BASE_DOMAIN=plugins.epicstaff.localhost` and
`DJANGO_REFRESH_COOKIE_SECURE=false`; [Run EpicStaff for plugin development](#run-epicstaff-for-plugin-development) has
the rest.

Chromium and Firefox resolve every `*.localhost` name to your machine by themselves. Safari uses the operating system's
resolver, which on current macOS does the same.

EpicStaff and its plugin hosts must share a registrable domain (`epicstaff.localhost` here): the sign-in inside
EpicStaff's frame relies on EpicStaff's session cookie being sent to EpicStaff from the plugin's frame, which browsers
allow only between hosts of the same site. Plain `localhost` for EpicStaff with `plugins.localhost` for plugins does
not work: those are two sites.

## Secure context

Signing in needs the Web Crypto API, which browsers offer only in a **secure context**: `https`, or plain `http` on
`localhost` and `*.localhost`. On any other plain `http` address (`http://weather.plugins.epicstaff.test`, a LAN IP)
`createPluginLogin` throws `insecure_context`.

## Safari

Test Safari against `*.test` names over HTTPS, or on a real domain:

1. Add `epicstaff.test` and `<id>.plugins.epicstaff.test` to `/etc/hosts` (pointing at `127.0.0.1`).
2. Make a local certificate authority and a wildcard certificate for `epicstaff.test` and `*.plugins.epicstaff.test`,
   trust the authority in your keychain, and run nginx with `NGINX_SSL_MODE=on`.
3. Set `DJANGO_FRONTEND_BASE_URL=https://epicstaff.test`, `PLUGINS_BASE_DOMAIN=plugins.epicstaff.test` and
   `DJANGO_REFRESH_COOKIE_SECURE=true`.

`http://*.test` is not a secure context, so the SDK refuses it. Plugin development mode, below, needs `.localhost`
names: on a `*.test` stack, install each change as a new version instead.

## Run EpicStaff for plugin development

You need Docker with Compose 2.24.4 or later, Python 3.12 or 3.13 with [uv](https://docs.astral.sh/uv/), and
Node.js 24.15 or later.

Write `src/.env` with the development defaults. This replaces a `src/.env` you already have; `make env-update DEV=1`
only adds the variables yours lacks.

```bash
python3 scripts/envtool.py --dev
```

Then set these in `src/.env`:

| Variable | Value |
|---|---|
| `PLUGINS_ENABLED` | `true` |
| `COMPOSE_PROFILES` | add `plugins`: `dev,chat,auditor,plugins` |
| `NGINX_SERVER_NAME` | `epicstaff.localhost` |
| `DJANGO_FRONTEND_BASE_URL` | `http://epicstaff.localhost` |
| `PLUGINS_BASE_DOMAIN`, `DJANGO_REFRESH_COOKIE_SECURE`, `NGINX_SSL_MODE`, `DJANGO_DEBUG` | Keep the development defaults: `plugins.epicstaff.localhost`, `false`, `off`, `true` |
| `PLUGINS_GATEWAY_SECRET`, `PLUGINS_NODE_KEY`, `PLUGINS_DB_SUPERUSER_PASSWORD`, `PLUGINS_DB_ADMIN_PASSWORD`, `PLUGINS_DB_BACKUP_PASSWORD` | Each the output of `openssl rand -hex 32` |
| `PLUGINS_TRUSTED_SIGNING_KEYS` | Optional: your key's entry, so your packages install as Trusted ([Create a signing key](sign-and-package.md#2-create-a-signing-key)) |
| `PLUGINS_DEV_MODE` | `true`: plugin development mode, below |
| `PLUGINS_DEV_API_PORT` | Keep `8082`, unless that port is taken on your machine |

and raise the login and refresh rates if you run the browser tests ([Login and refresh rates](#login-and-refresh-rates)).
[Enable the plugin platform](../operator/enable-plugins.md) describes every variable.

Start EpicStaff from `src/`, with both compose files:

```bash
cd src
docker compose -f docker-compose.yaml -f docker-compose.plugins-dev.yaml --env-file ./.env up -d
```

`docker-compose.plugins-dev.yaml` holds the three things only development needs, and that production must never
have:

- the name `host.docker.internal` for django_app, which Docker Desktop has built in and Linux does not;
- EpicStaff's **development API listener**, published on `127.0.0.1:${PLUGINS_DEV_API_PORT}` of your machine only,
  where a development backend calls EpicStaff's API;
- EpicStaff's ports 80 and 443 on `127.0.0.1` only, instead of every interface: with a development target set, a
  plugin's address serves ports of your machine, and nobody else on your network may reach them.

It replaces the port list of `docker-compose.yaml` with Compose's `!override`, which is why it needs Compose 2.24.4 or
later.

**Plugin development mode** lets a SuperAdmin serve an installed plugin's backend and page from ports on your machine.
It runs only on a deployment on your own machine: with `PLUGINS_DEV_MODE=true`, django_app refuses to start unless
`DJANGO_DEBUG=true`, the host of `DJANGO_FRONTEND_BASE_URL` is `localhost` or a `.localhost` name,
`PLUGINS_BASE_DOMAIN` is a `.localhost` name, and, under docker compose, the stack runs with
`docker-compose.plugins-dev.yaml` (which alone sets `PLUGINS_DEV_LOOPBACK_ONLY`; never put that in `.env`). A
`manage.py` run on the host is not checked for that file. epicstaff-nginx refuses the same way. What keeps the mode
local is that file's binding of EpicStaff's ports to `127.0.0.1`. The `.localhost` names only stop browsers on other
machines: a client that reaches a port can set the `Host` header by hand. Under compose, without the file, django_app and
epicstaff-nginx refuse to start in this mode.
[Plugin development mode](../operator/enable-plugins.md#plugin-development-mode) says exactly what it opens. Turn it
off again with `PLUGINS_DEV_MODE=false`, starting with `docker-compose.yaml` alone: what was routed to your machine is
then ignored, and its keys are refused.

Open `http://epicstaff.localhost` and go through first setup, which makes you the SuperAdmin.

## Install your plugin once

Development reroutes an **installed** plugin, so install your plugin once, as a package. Build the JS SDK and the
page:

```bash
npm --prefix plugin-sdk ci && npm --prefix plugin-sdk run build
npm --prefix plugin-samples/weather/spa ci && npm --prefix plugin-samples/weather/spa run build
```

then pack it as [Sign and package a plugin](sign-and-package.md) describes, upload it with **Upload plugin** under **Workspace → Plugins**,
approve it, and grant it to an organization: step 6 of [the tutorial](../tutorial/build-your-first-plugin.md#6-pack-approve-grant)
does it for Weather.

The installed version keeps running while you develop, and decides everything the plugin declares: its settings,
public paths, access and user permissions, and it runs the hooks and the migrations of the plugin's own database. A
change to one of those takes a new version ([Ship a change](#ship-a-change)).

## Develop the backend on your machine

### 1. Make a virtual environment for the plugin

At the plugin's root, never under `backend/`, which `pack` copies into the package as it finds it. Install the
backend's lock, then the SDK from the checkout, without dependencies: the lock already pins them.

```bash
uv venv --python 3.13 plugin-samples/weather/.venv
uv pip install --python plugin-samples/weather/.venv --require-hashes -r plugin-samples/weather/backend/requirements.lock
uv pip install --python plugin-samples/weather/.venv --no-deps ./src/plugin_sdk
```

Use the Python your manifest's `backend.python` names. The sample's `plugin-samples/weather/.gitignore` keeps `.venv/`
and development runtime files out of version control; give your plugin the same.

### 2. Download the development runtime file

As the SuperAdmin, open **Plugins → Weather → Development** and choose **Download development runtime file**. The file
holds keys that act for the plugin in every organization it is granted to, and its secret settings. Save it outside
your plugin's source, readable by you only:

```bash
mkdir -p ~/weather-dev
mv ~/Downloads/weather-development-runtime.json ~/weather-dev/
chmod 600 ~/weather-dev/weather-development-runtime.json
```

Each download revokes the keys of the one before. Download it again, to the same path, after the plugin is granted to
another organization or a suspended organization is resumed: the file is never updated by itself.

### 3. Run the backend

Weather keeps its data in a database, and its backend does not start without one: set up a local database first
([A database for the development backend](#a-database-for-the-development-backend)). Then, from the venv:

```bash
source plugin-samples/weather/.venv/bin/activate
epicstaff-plugin dev plugin-samples/weather --runtime-file ~/weather-dev/weather-development-runtime.json --port 8001 --database-url postgresql://weather_app:choose-a-password@127.0.0.1:5433/weather_development --apply-migrations
```

A plugin without a database needs only `--runtime-file` and `--port`. `dev` prints the backend's address, the
organizations the file holds keys for, and what to do in EpicStaff, and restarts the backend whenever you save a file
under `backend/src`. [`epicstaff-plugin dev`](../reference/cli.md#epicstaff-plugin-dev) lists every option.

### 4. Point the plugin at it

On the Development tab, set **Backend port** to `8001` and choose **Save**. Within about 10 seconds every request to the plugin's
`/api/` goes to your backend, with the same checks and the same signed gateway contexts as on the plugin node. People
who open the plugin see a banner saying it is served from a developer's machine, and the plugins list marks it
"Development". Calls your backend makes to EpicStaff appear in the organization's Plugin activity, marked
"Development".

**Stop development** on the same tab sends the plugin's requests to the installed backend again, and revokes the keys
of the runtime file. It asks you to confirm first, as **Download development runtime file** does, and so does
**Restart** on the Runtime tab. Ports you typed but did not save stay in the fields through a download and through a
stop that failed; a save or a stop that worked puts the stored ports back.

### What differs from the plugin node

| | Development backend |
|---|---|
| Hooks | Run on the installed version, on the plugin node: install, upgrade and organization removed hooks never reach your backend |
| Outbound requests | Your machine's network, with no allow-list: check that every host you call is in `outbound_hosts` before you ship |
| Database | Not the plugin's: a local one you pass, or none |
| Public paths, settings, access and user permissions | The installed version's |
| Keys | Development keys, valid only on the development API listener, only while development mode is on, and only until development stops, the file is downloaded again, or the plugin is suspended in the organization; resuming issues none, so download the file again |

[Runtime: a development backend](../reference/runtime.md#a-development-backend) lists the rest.

### On Linux

`host.docker.internal` is then the address of your machine on Docker's bridge, which the Development tab shows, not
`127.0.0.1`. Run the backend on that address, `--host <the address the Development tab shows>`, and let your firewall
accept connections from Docker's networks to the port.

## Develop the page against a development server

The page can come from a development server on your machine too, served at the plugin's own address: the frame's
address does not change, so signing in, navigation sync, the theme and EpicStaff's Back work as with the published
page.

The Weather sample's server watches `spa/src` and reloads the page when a file changes:

```bash
npm --prefix plugin-samples/weather/spa run dev
```

It listens on `127.0.0.1:5173` (`HOST` and `PORT` change that). On the Development tab, set **Frontend dev server
port** to `5173` and save, then reload the plugin in EpicStaff. The backend can stay the installed one, or be yours.

Any development server works if it:

- **listens where Docker can reach it**: on macOS `127.0.0.1` will do; on Linux, the address the Development tab shows,
  with your firewall accepting connections from Docker's networks;
- **accepts `localhost` as its host**: EpicStaff sends `Host: localhost:<port>`, which esbuild, Vite and webpack's
  development servers accept without any setting, and passes the plugin's host name on as `X-Forwarded-Host`. The
  browser's `Origin` stays the plugin's origin;
- **keeps live reload on the page's own host and port**, connecting to the address the page was loaded from, never to
  `localhost:<port>` directly. WebSocket and server-sent events pass through;
- **answers every client route with the page**, as the published page does, and uses relative paths.

EpicStaff never sends the development server the browser's cookies, its `Authorization` header, an API key or a
gateway context. From its answers it drops `Set-Cookie`, `Clear-Site-Data`, `X-Frame-Options` and
`Content-Security-Policy`, keeps the caching headers, and adds the plugin host's own security headers. When the server
cannot be reached, the page says "The development server for this plugin cannot be reached.", and while the plugin is
being upgraded it shows the maintenance page instead.

Anyone who can reach this EpicStaff can reach the development server through the plugin's address. With the
development compose file, EpicStaff's ports are bound to `127.0.0.1`, so that is only you; the `.localhost` names alone
would not stop another machine that reaches the port. [Frontend in the frame](frontend-in-the-frame.md) covers how the page's own code behaves
behind a development server.

## A database for the development backend

A development backend never reaches the plugin's own database on the deployment. Give it a local PostgreSQL 16 or
later instead, set up the way the plugin node sets one up, with two roles:

- a login role, `<name>_app`, that owns the database, and so also owns every table your migrations create;
- a role `<name>_job` that cannot log in, granted to the login role `WITH INHERIT FALSE, SET TRUE`, which the SDK's
  `job_transaction` switches to.

Neither may be a superuser or bypass row-level security: `epicstaff-plugin dev` refuses those, and a setup of other
roles, and prints the SQL that creates the right ones.

Without a PostgreSQL of your own, start a throwaway one in Docker and open `psql` as its superuser:

```bash
docker run -d --name weather-dev-db -e POSTGRES_PASSWORD=choose-a-superuser-password -p 127.0.0.1:5433:5432 postgres:17
docker exec -it weather-dev-db psql -U postgres
```

As a superuser, create the two roles and the database. For Weather:

```sql
CREATE ROLE weather_job NOLOGIN;
CREATE ROLE weather_app LOGIN PASSWORD 'choose-a-password';
GRANT weather_job TO weather_app WITH INHERIT FALSE, SET TRUE;
CREATE DATABASE weather_development OWNER weather_app;
```

Then pass `--database-url postgresql://weather_app:choose-a-password@127.0.0.1:5433/weather_development` and
`--apply-migrations` to `epicstaff-plugin dev`, as in [Run the backend](#3-run-the-backend). The URL may leave the
password out, `postgresql://weather_app@127.0.0.1:5433/weather_development`: libpq then reads it from `PGPASSWORD` or
`~/.pgpass`, which keeps it out of `ps` and your shell history.

`--apply-migrations` applies the files of `database/migrations/` the database's ledger does not list yet, as the node
does ([`epicstaff-plugin dev`](../reference/cli.md#a-local-database)). Unlike on the node, the login role owns the
tables, so it can do what only the owner can there: test your grants against the node's three roles before you ship
([Write database migrations](database-migrations.md#test-your-migrations-before-you-upload)). The data is yours alone:
the development backend does not see the installed plugin's rows, and the installed plugin does not see yours.

`dev` warns about two more things here. When tables the login role owns do not FORCE ROW LEVEL SECURITY, their policies
do not apply to your backend locally, though they do on EpicStaff, where the app role owns no table: add `ALTER TABLE …
FORCE ROW LEVEL SECURITY` to your migrations, or test against the node's roles. And when the runtime file is inside a
git work tree that no ignore rule covers, it warns that the file, which holds keys, could be committed.

## Ship a change

1. Raise `version` in the manifest, and add a migration file for every schema change.
2. Pack and sign the new version ([Sign and package a plugin](sign-and-package.md)).
3. Upload it with **Upload plugin** on the Plugins list and upgrade to it ([Bring organizations to a new version](upgrade-hook.md),
   [the plugin lifecycle](../explanation/lifecycle.md#upgrades)).
4. Choose **Stop development** on the Development tab, so the plugin is served from its new package again.

## Tests

| What | Command |
|---|---|
| The JS SDK and the platform callback pages (Node, no browser) | `npm --prefix plugin-sdk test` |
| The Weather page (type check and build) | `npm --prefix plugin-samples/weather/spa run build` |
| Sign-in and popups in Chromium, Firefox and WebKit, against your running stack | [The browser tests](#the-browser-tests) |
| Everything above on a throwaway stack, with the platform's smoke checks and development mode | [The stack run](#the-stack-run) |

### The browser tests

The browser checks in `plugin-sdk/test-browser/` sign a person in inside EpicStaff and on the plugin's own address,
renew, end the session, and run both popup paths, against the Weather sample. They need Weather installed, running and
granted to two organizations, and people in them. The seed sets that up on your running stack through EpicStaff's API,
from a Weather package you packed:

```bash
npm --prefix plugin-sdk/test-browser ci
npx --prefix plugin-sdk/test-browser playwright install chromium firefox webkit
E2E_PACKAGE=/path/to/weather-0.7.0.esplugin E2E_SUPERADMIN_EMAIL=you@example.com E2E_SUPERADMIN_PASSWORD='…' \
    npm --prefix plugin-sdk/test-browser run e2e:seed
npm --prefix plugin-sdk/test-browser run e2e
```

The seed uses EpicStaff's HTTP API only. It runs first setup on a fresh deployment, or signs the SuperAdmin in. Before
it writes anything it checks `E2E_PACKAGE` and everything else that can stop it: a plugin it cannot take further, a
deactivated organization, a person who exists but has no password in the stack file. Then it creates the organizations
"E2E Acme", "E2E Bravo" and "E2E Cobalt" and their people, or reuses them, installs Weather when it is not installed
yet, and grants it to Acme and Cobalt. It writes what the tests need to a stack file, readable by you only, and never
prints a password. It writes the file as soon as the people exist, and again once it has found the flow.

A stack file with `"flow_id": null` means the seed stopped after the people. Run it again: it reuses their passwords.
Run it again at any time: it reuses what exists. It never changes a password, so it stops when one of its people
exists but the stack file has no password for them.

| Variable | Default |
|---|---|
| `E2E_EPICSTAFF_URL` | `http://epicstaff.localhost` |
| `E2E_PLUGIN` | `weather` |
| `E2E_PLUGIN_URL` | `http://weather.plugins.epicstaff.localhost` |
| `E2E_PACKAGE` | The `.esplugin` the seed installs; needed only while the plugin is not installed |
| `E2E_SUPERADMIN_EMAIL`, `E2E_SUPERADMIN_PASSWORD` | Required by the seed |
| `E2E_STACK_FILE` | `.stack.json` in the suite |

The tests read their own variables first, then the stack file, so a stack you set up by hand works too:
`E2E_EMAIL` and `E2E_PASSWORD` for a person who is a member of both organizations with View on Weather, and
`E2E_ORG_A_ID`, `E2E_ORG_A_NAME`, `E2E_ORG_C_ID` and `E2E_ORG_C_NAME` for the organizations.

Add `--project=webkit` (or `chromium`, `firefox`) to run one engine. Against the HTTPS stack of [Safari](#safari), set
`E2E_EPICSTAFF_URL=https://epicstaff.test` and `E2E_PLUGIN_URL=https://weather.plugins.epicstaff.test`; the browsers
accept its local certificate, and the seed trusts it when `NODE_EXTRA_CA_CERTS` names your local certificate authority.
A failing test is never retried, and keeps a trace. With `CI` set, the suite also refuses `test.only` and writes an
HTML report to `playwright-report/`.

Each test signs in for itself instead of reusing a saved browser state: EpicStaff replaces the refresh cookie at every
renewal and refuses the old one, so a saved state is signed out once the first test has used it.

### Login and refresh rates

The suite signs the person in seven times per browser, 21 times for a run of all three, and every EpicStaff page it
opens renews EpicStaff's session, all from your address within a minute. EpicStaff's default throttles
(`DJANGO_LOGIN_THROTTLE_RATE=5/min`, `DJANGO_LOGIN_IP_THROTTLE_RATE=20/min`, `DJANGO_TOKEN_REFRESH_THROTTLE_RATE=30/min`)
stop a run part-way: a test then waits on a login form that says "Too many login attempts" until it times out. On
your local stack only, raise them in `src/.env`:

```bash
DJANGO_LOGIN_THROTTLE_RATE=100/min
DJANGO_LOGIN_IP_THROTTLE_RATE=300/min
DJANGO_TOKEN_REFRESH_THROTTLE_RATE=600/min
```

and recreate django_app, which reads them only when it starts (from `src/`):

```bash
docker compose -f docker-compose.yaml -f docker-compose.plugins-dev.yaml --env-file ./.env up -d django_app
```

### The stack run

`.github/scripts/plugin_platform_e2e.sh` runs it all on a throwaway stack of its own: it writes a temporary
environment, builds and starts the services the run needs, packs and signs Weather for your machine's architecture,
seeds it, runs the browser tests in all three engines and the platform's smoke checks, recreates the stack in
development mode and checks that, and last runs the checks that change the stack for good. It stops at the first
failure, prints how long each stage took, and removes the stack, its volumes and the images it built at the end.

```bash
bash .github/scripts/plugin_platform_e2e.sh
```

It needs Docker with Compose 2.24.4 or later, python3 with PyYAML, uv, Node.js 24.15 or later with npm, and curl, and
network access for images, packages and browsers.

- **Bring your own stack down first.** The script refuses to start while containers with the stack's names exist,
  running or stopped, or while the plugins subnet `10.235.252.0/24` or the ports 80, 443 or `PLUGINS_DEV_API_PORT` on
  `127.0.0.1` are taken. It never stops or removes another stack.
- **Host names.** `epicstaff.localhost` and `weather.plugins.epicstaff.localhost` must resolve to `127.0.0.1` for the
  tools it runs. When they do not, it prints the line to add to `/etc/hosts`,
  `127.0.0.1 epicstaff.localhost weather.plugins.epicstaff.localhost`, and a `sudo tee -a /etc/hosts` command that adds
  it.
- **Settings**, all optional:

  | Variable | Default |
  |---|---|
  | `E2E_KEEP_STACK` | `false`. `true` leaves the stack running, and prints its environment file and how to remove it |
  | `E2E_ARTIFACTS_DIR` | A directory named after the run in `TMPDIR`, printed at the end: where a failed run leaves the browser report, the traces and the containers' logs, with the run's secrets replaced |
  | `E2E_PROJECT` | `epicstaff-plugin-e2e`, the Compose project |

  Any other variable of `src/env.yaml` set in your shell overrides the run's own value, except `IMAGE_TAG`,
  `COMPOSE_PROFILES`, `PLUGINS_NETWORK_SUBNET` and the secrets, which every run sets itself.

The workflow `.github/workflows/plugin-platform-stack.yml` runs the same script on pull requests that change the
plugin platform, and on request. It is not a required check.
