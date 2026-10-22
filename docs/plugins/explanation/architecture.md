# Architecture

How the parts of the plugin platform fit together, and what happens when a plugin's page loads,
signs someone in, calls its backend, and when the backend calls EpicStaff or runs a hook. Each
part is described in full on the page this one links to.

## The parts

```
browser
  │
  ▼
epicstaff-nginx
  ├─ EpicStaff's host ─────────▶ frontend (EpicStaff's web app) and django_app (EpicStaff's API)
  │
  └─ <id>.<plugins base domain>, one host per plugin
       ├─ the page's files ─────▶ the plugin's published page, served by nginx
       ├─ /.well-known/epicstaff/ ─▶ the platform config (from django_app) and the sign-in callback pages
       └─ /api/** ─▶ gateway check: django_app decides ─▶ es_plugins, the plugin node
                                                            └─ one process per plugin, each under a Unix user of its own
                                                                 ├─▶ plugins_db: the plugin's own database
                                                                 ├─▶ plugins_egress ─▶ the hosts it declares, HTTPS on 443
                                                                 └─▶ nginx's internal listener ─▶ django_app: EpicStaff's API
```

| Part | What it does |
|---|---|
| **django_app** | **Decides.** It keeps the plugins, their packages, reviews, approvals, grants, settings, limits and service accounts; answers every gateway check; signs the gateway contexts and hook calls; issues keys, keeping only their hashes; tells the plugin node what to run; and records activity |
| **epicstaff-nginx** | **Enforces.** It serves each plugin on its own host, asks django_app about every request to a plugin's `/api/` before passing it on, strips browser credentials on the way, and refuses requests from the plugin network on every public host. Its internal listener is the one way from the plugin network to EpicStaff's API ([How plugin backends are kept apart](../operator/enable-plugins.md#how-plugin-backends-are-kept-apart)) |
| **es_plugins**, the plugin node | **Runs plugin code.** It installs each backend offline from its package, runs it as a process of its own under its own Unix user, checks its health, applies its limits, writes its runtime file, calls its hooks, and sets up and backs up its database ([Runtime](../reference/runtime.md)) |
| **plugins_db** | A PostgreSQL server with one database and three roles per plugin. Only the plugin node and the plugin backends reach it; django_app never connects to it ([Plugin database](../reference/database.md)) |
| **plugins_egress** | The egress proxy: the only way from a plugin backend to the internet, to the hosts its manifest declares ([Call the internet from your backend](../how-to/outbound-hosts.md)) |
| **frontend** | EpicStaff's web app: the plugins in the left bar, the frame a plugin's page shows in, and the SuperAdmin's plugin pages |

A plugin without a backend needs only nginx and django_app: its page is static files.

## Five flows

### Loading a plugin's page

1. A person opens the plugin from EpicStaff's left bar, which lists the plugins whose View they hold in the
   organization ([Give people permissions](../how-to/user-permissions.md)).
2. EpicStaff's address `/plugins/<id>/<path>` shows a frame of `https://<id>.<plugins base domain>/<path>`, with the
   organization in `es_org` ([Frame protocol](../reference/frame-protocol.md#the-frame)).
3. nginx serves the plugin's published files, from the approved package, and lets only EpicStaff frame them.
4. The page loads its platform config from its own `/.well-known/epicstaff/config.json`, which nginx asks django_app
   for ([JS SDK](../reference/js-sdk.md#platform-config)).
5. The page and EpicStaff's frame run the frame protocol: the theme, navigation and the organization
   ([Handshake](../reference/frame-protocol.md#handshake)).

### Signing in

1. The JS SDK sends the browser, in a hidden frame first, to EpicStaff's authorize endpoint with a fresh PKCE
   challenge.
2. django_app reads EpicStaff's own session cookie, checks that the person may use the plugin in the organization,
   and redirects to the plugin's own callback page with a one-time code.
3. The page exchanges the code at EpicStaff's token endpoint for a plugin login token that lives 15 minutes. That
   exchange is the one call to EpicStaff's API a plugin page can make.
4. The SDK keeps the token in memory, sends it only to the plugin's own `/api/`, and renews it before it expires
   ([Token exchange](../reference/token-exchange.md)).

### A request to the plugin's backend

1. The page calls `https://<id>.<plugins base domain>/api/…` with the token, or a public path without one.
2. nginx asks django_app's gateway check, with the request's headers only: whether the plugin is in service and up,
   whether the path is canonical, and then whether it is a public path within its limits, or carries a valid token of
   a person who may use the plugin ([Serve public paths](../how-to/public-paths.md#what-the-gateway-checks-in-order),
   [Gateway context](../reference/gateway-context.md#who-is-asking-user-contexts)).
3. Refused, the client gets the gateway's answer ([Error codes](../reference/error-codes.md#gateway-codes)). Allowed,
   nginx forwards the request to the plugin's process with a gateway context EpicStaff signed for exactly this request,
   without the browser's cookies, the token or EpicStaff's API keys.
4. The Python SDK in the process verifies the context before the request reaches the plugin's code
   ([Verification](../reference/gateway-context.md#verification)).

### The backend calling EpicStaff

1. The backend reads the organization's service-account key from its runtime file
   ([Runtime](../reference/runtime.md#service-accounts)).
2. It calls the runtime file's `epicstaff_api_url`, nginx's internal listener on the plugin network, which adds the
   gateway secret no caller can set and serves only `/api/`, without the login, administration and gateway routes.
3. django_app takes the key as the plugin's service account in that one organization, allows exactly the plugin's
   declared access, checks the person when the call is made on someone's behalf, and records every change as plugin
   activity ([Service account API](../reference/service-account-api.md)).

### A lifecycle hook

1. A SuperAdmin grants the plugin to an organization, an upgrade reaches the organization, or the organization's data
   is to be deleted: django_app records a hook job ([Hook API](../reference/hook-api.md)).
2. Once the plugin's process is running and healthy, and holds the organization's key where the hook needs one, the
   plugin node asks django_app for a call signed for this one hook.
3. The node posts it to the process over the loopback interface, at `/_epicstaff/hooks/<kind>`. nginx never forwards
   those paths. The Python SDK verifies the signed call and runs the handler
   ([Verification](../reference/hook-api.md#verification)).
4. The node reports the answer, and django_app moves the organization on, or tries the hook again on its schedule.

## Where things live

| What | Where |
|---|---|
| Uploaded packages | EpicStaff's storage, in the plugins bucket |
| Published pages | A volume django_app writes when a package is approved, and nginx serves from |
| Plugins, reviews, grants, settings (secrets encrypted), limits, service accounts | EpicStaff's database |
| Service-account keys | Only their hashes in EpicStaff's database. The keys themselves are only in runtime files |
| Runtime files | On the plugin node, one per plugin, readable only by the plugin's own Unix user, rewritten by the node when keys or grants change ([Runtime file](../reference/runtime.md#runtime-file)) |
| Backends' code, virtual environments, files and logs | The plugin node's volume |
| Plugin databases | plugins_db, one database per plugin; the backups taken before upgrades on the plugin node's volume |
| Activity | EpicStaff's database, kept after the plugin and its organizations are gone ([Activity](../reference/service-account-api.md#activity)) |

[Where plugin data lives](../operator/enable-plugins.md#where-plugin-data-lives) names each volume, and what to back
up.

## Scale

In this version a deployment has one plugin node and one plugin database server. Every plugin backend runs in the
node's container and shares its CPUs and memory, and every plugin database shares the server's connections and disk
([Limits](../reference/limits.md), [Accepted risks](accepted-risks.md#plugins-on-one-node-share-a-container)).
EpicStaff records which node runs each plugin.

Every request to a plugin's `/api/` waits for django_app's gateway check, so a deployment with real plugin traffic
runs more than one Django worker ([Settings](../operator/enable-plugins.md#3-settings), `DJANGO_SGI_WORKERS`).

## Development mode

On a deployment on a developer's own machine, and nowhere else, a SuperAdmin can point an installed plugin at ports
on that machine:

- **a backend port:** the gateway check names the developer's backend, at `host.docker.internal:<port>`, as the
  upstream of the plugin's `/api/`, after the same checks as always;
- **a frontend development server port:** nginx asks django_app about each request for the plugin's page, and passes
  it to the development server instead of serving the published files.

The frame's address, the sign-in, the gateway contexts and the platform paths stay as they are. A development backend
calls EpicStaff with development keys, through a development API listener on the machine's loopback. Hooks still run
on the installed version, on the plugin node. [Local development](../how-to/local-development.md) shows how to use
it, and [Plugin development mode](../operator/enable-plugins.md#plugin-development-mode) what it opens.
