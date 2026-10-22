# EpicStaff plugins

A plugin is a product that runs on top of EpicStaff. A SuperAdmin installs it once for the whole
deployment and grants it to organizations; their members then open it from EpicStaff's left bar,
where it shows inside EpicStaff's layout in a frame, on an address of its own
(`<id>.<plugins base domain>`), with EpicStaff's theme. A plugin may also have a Python backend,
which EpicStaff runs as a process of its own on the deployment's plugin node and reaches through
its gateway at `<id>.<plugins base domain>/api/`.

These pages are for people who build plugins and for operators who run them.

## Before you start

> Plugins are meant to be open code, and EpicStaff does not check that they are. Anyone who can reach a deployment can download a plugin's frontend files. Every administrator of every deployment that installs a plugin can read the whole package, including its backend code. EpicStaff is not responsible for that exposure.

- A plugin's frontend files are public, like EpicStaff's own: the page has to load before anyone
  can log in. Keep secrets out of them.
- A plugin is a single-page app built to static files, in any framework, and optionally a Python
  ASGI backend. A backend may keep its data in a PostgreSQL database of its own
  ([Plugin database](reference/database.md)), and may call the internet hosts its manifest
  declares, over HTTPS through the deployment's egress proxy
  ([Call the internet from your backend](how-to/outbound-hosts.md)). Every other outbound request
  is refused.
- People log in to a plugin through EpicStaff, never with a password of the plugin's own: the
  [JS SDK](reference/js-sdk.md) gets a plugin login token for the person and the organization
  ([token exchange](reference/token-exchange.md)) and sends it to the plugin's backend, which
  receives a signed [gateway context](reference/gateway-context.md) instead. A backend's
  [public paths](how-to/public-paths.md) need no login.
- A backend calls EpicStaff's API as the plugin's service account in each organization it is
  granted to, within the `access` its manifest declares, on its own or on behalf of a person
  ([Service account API](reference/service-account-api.md)). Org Admins see what it does there.
- Your plugin page must also work when opened directly at its own address, and must not hard-code
  that address: load the platform config from `/.well-known/epicstaff/config.json` and use
  relative paths.

## Build a plugin

| Page | What it covers |
|---|---|
| [Build your first plugin](tutorial/build-your-first-plugin.md) | A tutorial: the Weather sample from manifest to a running backend that creates its flow when installed and runs it for people |
| [Manifest and package format](reference/manifest.md) | Every manifest field and rule, the package layout, caps, `CONTENTS.json`, error locations |
| [`manifest.schema.json`](reference/manifest.schema.json) | The manifest as JSON Schema, for editors and your own checks |
| [Frame protocol](reference/frame-protocol.md) | How the plugin page and EpicStaff talk: handshake, navigation sync, theme tokens |
| [JS SDK](reference/js-sdk.md) | `@epicstaff/plugin-sdk` for the page: the frame, logging people in, calling the backend, popups |
| [Frontend in the frame](how-to/frontend-in-the-frame.md) | Building the page so it works framed and opened directly, logged in, with the person's organization |
| [Token exchange](reference/token-exchange.md) | How a person logs in to a plugin: authorize, the code exchange, the plugin login token, the organization chooser |
| [External callbacks](how-to/external-callbacks.md) | Connecting an outside service (OAuth in a popup) and getting its answer back to the page |
| [Local development](how-to/local-development.md) | Running a plugin against a local EpicStaff, over `*.localhost` or HTTPS |
| [Sign and package a plugin](how-to/sign-and-package.md) | `epicstaff-plugin validate`, `keygen`, `pack` (with wheels for a backend), `sign`, `verify` |
| [Trust and signing](explanation/trust-and-signing.md) | What Trusted and Untrusted mean, and how signatures are checked |
| [Give people permissions](how-to/user-permissions.md) | `user_permissions`, built-in role defaults, custom roles in the Roles matrix and their ceiling |
| [Python SDK](reference/python-sdk.md) | `epicstaff-plugin` for backends: serving, the context check, the runtime configuration, testing |
| [Runtime](reference/runtime.md) | How a backend runs: environment, runtime file, file system, what other plugins can see |
| [Plugin database](reference/database.md) | The database a backend gets: when it is set up, its names, roles and grants, the environment, limits, the migration ledger |
| [Write database migrations](how-to/database-migrations.md) | SQL migrations in the package, role placeholders, keeping organizations apart with row-level security, testing them |
| [Call the internet from your backend](how-to/outbound-hosts.md) | `outbound_hosts`, the egress proxy, clients that read the proxy from the environment, what a refusal looks like |
| [Gateway context](reference/gateway-context.md) | The signed statement every backend request carries (public or a logged-in person), and how it is verified |
| [Serve public paths](how-to/public-paths.md) | Paths reached without a login: canonical paths, body caps, rate limits |
| [Use settings](how-to/settings.md) | Settings a SuperAdmin fills in, secrets, required settings |
| [Declare what your backend may do](how-to/declare-access.md) | `access`: which actions each call needs, what a declaration never gives, what administrators see |
| [Call EpicStaff from your backend](how-to/call-epicstaff-from-the-backend.md) | The SDK's EpicStaff client: per-organization keys, calling on behalf of a person, people lookups, running flows |
| [Service account API](reference/service-account-api.md) | The service account and its keys, what it may do, on behalf of a person, `/api/plugin-runtime/`, activity |
| [Run code when an organization gets your plugin](how-to/install-hook.md) | The install hook: registering a handler, idempotency, failures and retries |
| [Delete your data when an organization leaves](how-to/org-removed-hook.md) | The organization removed hook: when it runs, deleting only your own data, idempotency, retries and skip |
| [Bring organizations to a new version](how-to/upgrade-hook.md) | The upgrade hook: when it runs, `previous_version`, bringing an organization from any earlier version, retries |
| [Compatibility and versioning](reference/compatibility-and-versioning.md) | Version order, what a new version may and may not change, what needs the SuperAdmin's approval, how an upgrade goes |
| [The plugin lifecycle](explanation/lifecycle.md) | A plugin's states in an organization, suspending and resuming, the grace period, deleting a grant's data, uninstalling, reinstalling and deleting a plugin, upgrades and their backups, deleting an organization |
| [Accepted risks](explanation/accepted-risks.md) | What installing a plugin means trusting, what isolation there is and is not, and what data deletion can leave behind |
| [Hook API](reference/hook-api.md) | How EpicStaff calls a lifecycle hook: the signed assertion, the body, the answer |
| [Limits](reference/limits.md) | Memory, CPU, the request rate and the other limits, the platform maximums, what is enforced |
| [Error codes](reference/error-codes.md) | Every code the plugin API, the login and the gateway answer with |

The sample plugin `plugin-samples/weather/` has a vanilla TypeScript app using the JS SDK
(`plugin-sdk/`) and a FastAPI backend using the Python SDK (`src/plugin_sdk/`).

## Run plugins

| Page | What it covers |
|---|---|
| [Enable the plugin platform](operator/enable-plugins.md) | HTTPS, wildcard DNS and certificate, the plugin node, settings, start-up checks, trusted signing keys |

## Compatibility

A manifest names the version of each platform contract it is written for. This version of
EpicStaff supports:

| Contract | Version | Status |
|---|---|---|
| Manifest (`manifest_version`) | 1 | Supported. A `database` section gives the backend a database of its own; `outbound_hosts` are the only hosts it can reach, through the egress proxy |
| Frame protocol (`platform.frame_protocol`) | 1 | Supported |
| Gateway context (`platform.gateway_context`) | 1 | Supported: `public` mode on public paths, `user` mode for logged-in people |
| Login protocol (`plugin-sdk/contracts/login-protocol.json`, `protocol`) | 1 | Supported, for plugins with a backend |
| Hook API (`platform.hook_api`) | 1 | Supported for `install`, `upgrade` and `org_removed` |
| Service account API (`/api/plugin-runtime/`) | 1 | Supported |
| Runtime file (`format`) | 1 | Supported |
| Backend Python (`backend.python`) | 3.12, 3.13 | Supported |
| Package signature | minisign, pre-hashed Ed25519 | Supported |

| Upgrades | — | Supported: a SuperAdmin approves each newer version, which backs the database up before its migrations. See [compatibility and versioning](reference/compatibility-and-versioning.md) |
