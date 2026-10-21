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
  ASGI backend. This version does not offer plugin databases yet: a package that declares one is
  refused, and the manifest format already describes it, so manifests will not change when it
  arrives.
- People log in to a plugin through EpicStaff, never with a password of the plugin's own: the
  [JS SDK](reference/js-sdk.md) gets a plugin login token for the person and the organization
  ([token exchange](reference/token-exchange.md)) and sends it to the plugin's backend, which
  receives a signed [gateway context](reference/gateway-context.md) instead. A backend's
  [public paths](how-to/public-paths.md) need no login.
- Your plugin page must also work when opened directly at its own address, and must not hard-code
  that address: load the platform config from `/.well-known/epicstaff/config.json` and use
  relative paths.

## Build a plugin

| Page | What it covers |
|---|---|
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
| [Gateway context](reference/gateway-context.md) | The signed statement every backend request carries (public or a logged-in person), and how it is verified |
| [Serve public paths](how-to/public-paths.md) | Paths reached without a login: canonical paths, body caps, rate limits |
| [Use settings](how-to/settings.md) | Settings a SuperAdmin fills in, secrets, required settings |
| [Limits](reference/limits.md) | Memory, CPU and the other limits, the platform maximums, what is enforced |
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
| Manifest (`manifest_version`) | 1 | Supported. A `database` section is refused with `plugin_feature_unavailable`; `access`, `outbound_hosts` and `hooks` are accepted and shown at review, but not used yet |
| Frame protocol (`platform.frame_protocol`) | 1 | Supported |
| Gateway context (`platform.gateway_context`) | 1 | Supported: `public` mode on public paths, `user` mode for logged-in people |
| Login protocol (`plugin-sdk/contracts/login-protocol.json`, `protocol`) | 1 | Supported, for plugins with a backend |
| Hook API (`platform.hook_api`) | 1 | Reserved for lifecycle hooks; declare `1` |
| Runtime file (`format`) | 1 | Supported |
| Backend Python (`backend.python`) | 3.12, 3.13 | Supported |
| Package signature | minisign, pre-hashed Ed25519 | Supported |

A plugin that has been approved cannot be replaced by a new version yet; upgrades come later.
