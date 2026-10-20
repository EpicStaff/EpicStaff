# EpicStaff plugins

A plugin is a product that runs on top of EpicStaff. A SuperAdmin installs it once for the whole
deployment and grants it to organizations; their members then open it from EpicStaff's left bar,
where it shows inside EpicStaff's layout in a frame, on an address of its own
(`<id>.<plugins base domain>`), with EpicStaff's theme.

These pages are for people who build plugins and for operators who run them.

## Before you start

> Plugins are meant to be open code, and EpicStaff does not check that they are. Anyone who can reach a deployment can download a plugin's frontend files. Every administrator of every deployment that installs a plugin can read the whole package, including its backend code. EpicStaff is not responsible for that exposure.

- A plugin's frontend files are public, like EpicStaff's own: the page has to load before anyone
  can log in. Keep secrets out of them.
- This version of EpicStaff installs **frontend-only plugins**: a single-page app built to static
  files, in any framework. Packages that declare a backend or a database are refused for now; the
  manifest format already describes them, so manifests will not change when they arrive.
- Your plugin page must also work when opened directly at its own address, and must not hard-code
  that address: load the platform config from `/.well-known/epicstaff/config.json` and use
  relative paths.

## Build a plugin

| Page | What it covers |
|---|---|
| [Manifest and package format](reference/manifest.md) | Every manifest field and rule, the package layout, caps, `CONTENTS.json`, error locations |
| [`manifest.schema.json`](reference/manifest.schema.json) | The manifest as JSON Schema, for editors and your own checks |
| [Frame protocol](reference/frame-protocol.md) | How the plugin page and EpicStaff talk: handshake, navigation sync, theme tokens |
| [Sign and package a plugin](how-to/sign-and-package.md) | `epicstaff-plugin validate`, `keygen`, `pack`, `sign`, `verify` |
| [Trust and signing](explanation/trust-and-signing.md) | What Trusted and Untrusted mean, and how signatures are checked |

The sample plugin `plugin-samples/weather/` is a complete frontend-only plugin: a vanilla
TypeScript app using the JS SDK (`plugin-sdk/`).

## Run plugins

| Page | What it covers |
|---|---|
| [Enable the plugin platform](operator/enable-plugins.md) | HTTPS, wildcard DNS and certificate, settings, start-up checks, trusted signing keys |

## Compatibility

A manifest names the version of each platform contract it is written for. This version of
EpicStaff supports:

| Contract | Version | Status |
|---|---|---|
| Manifest (`manifest_version`) | 1 | Supported. `backend` and `database` sections are refused with `plugin_feature_unavailable` |
| Frame protocol (`platform.frame_protocol`) | 1 | Supported |
| Gateway context (`platform.gateway_context`) | 1 | Reserved for plugin backends; declare `1` |
| Hook API (`platform.hook_api`) | 1 | Reserved for plugin backends; declare `1` |
| Package signature | minisign, pre-hashed Ed25519 | Supported |

A plugin that has been approved cannot be replaced by a new version yet; upgrades come later.
