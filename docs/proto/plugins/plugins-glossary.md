---
id: plugins-glossary
title: Plugins glossary
type: glossary
status: draft
tags: [plugins, prototype, terms]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-prd, plugins-rules, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugin-bridge-v2, plugin-author-tooling, plugins-api-contract, plugins-code-map]
---

# Plugins glossary

Precise meanings for the words used across the Plugins docs ([[plugins-prd]], [[plugins-architecture]]).

## Plugins and their parts

| Term | Means | Applies to | Is NOT |
|---|---|---|---|
| **Plugin** | A mini-app installed into one organization: EpicStaff resources (its backend) + an optional frontend + an access list (the contract between them) | The `Plugin` row and everything linked to it | An identity or service account; a code extension of EpicStaff itself |
| **Internal plugin** | A plugin whose file is uploaded to and hosted by EpicStaff | Everything in this prototype | A statement about who wrote it (authorship is not checked in v1) |
| **External plugin** | A plugin that runs on its own servers and calls the EpicStaff API | Future work | Supported today |
| **Plugin file** (package) | The `.zip` an admin installs: `plugin.json`, `resources.json`, `knowledge/`, `files/`, `ui/` ([[plugin-package-format]]) | Install and inspect | A plain EpicStaff export file (that is only `resources.json`) |
| **Manifest** | `plugin.json` — identity, versions, secret slots and bindings, knowledge, storage files, access list, frontend entry | Validation at inspect/install | Where resources are defined (that is `resources.json`) |
| **Plugin id** | The stable `id` in the manifest, e.g. `chat-admin`; one install per organization | Duplicate detection; name prefixes; future updates | The database id used in URLs (`/api/plugins/{id}/` and `/plugins/<id>/…` take the database id) |
| **Plugin resource** | A row the plugin's install **created**, recorded in the `PluginResource` registry with the plugin's own type name | Suspend, delete, status checks | A resource the organization already had (install never reuses those) |
| **Force-create** | Import mode that always creates new rows for plugin-owned types instead of reusing matching ones | Install | The importer's default behaviour |
| **Plugin key-value table** | A key-value table the plugin ships as a definition and installs as `<plugin_id>__<name>`; its flows write it, its app may read it | Chat Admin's `chat_admin__conversations` | A table the organization already had (a plugin flow may never use one) |
| **Secret slot** | A named, described placeholder for a secret the admin types at install; stored as an organization secret `<PLUGIN>__<SLOT>` | Install, the Secrets dialog | A secret value inside the file (never allowed) |
| **Secret binding** | Manifest instruction putting a slot's secret into a field of a shipped config, e.g. `LLMConfig.api_key_secret` | Install | A lookup by secret name in code (rejected in v1) |
| **Secret destination** | Where a slot's value will be sent: a provider's standard endpoint or a custom host | Install review, Secrets dialog | A guarantee about the remote service |

## The frontend and the bridge

| Term | Means | Applies to | Is NOT |
|---|---|---|---|
| **Plugin frontend** | The plugin's own UI, served from its `ui/` files into a sandboxed iframe inside EpicStaff's shell at `/plugins/<id>/…` | Users with `plugins:use` | Part of the EpicStaff app's code, or trusted |
| **Plugin page** | A simple, single-screen frontend speaking bridge v1 (the chat-bot sample) | `bridge: 1` | A multi-screen app |
| **Plugin app** | A full frontend application built with any SPA framework, with its own screens and deep links, speaking bridge v2 (the Chat Admin sample) | `bridge: 2` | Code loaded into EpicStaff's own bundle |
| **Host** | The EpicStaff app around the plugin frontend; it owns the bridge, enforces the access list, owns browser history and calls the API as the user | Every bridge call | A server component |
| **Bridge** | The postMessage + MessagePort protocol between frontend and host. Versioned; every shipped version is frozen: v1 ([[plugin-bridge-v1]]) runs flows and watches runs, v2 ([[plugin-bridge-v2]]) adds `kv.*`, `nav.*` and `theme.changed` | Frontend ↔ host | An HTTP API the frontend calls directly |
| **Access list** | The manifest's `access[]`: which flows and key-value tables the frontend may touch, under which aliases, with which actions | The bridge's access policy | A permission grant to users (user permissions come from roles) |
| **Alias** | The name a frontend uses for a resource on its access list, e.g. `chat`, `conversations` | Every bridge call | A database id (the frontend never sees or sends ids) |
| **Page-scoped session** | A run the open frontend started via `flows.run`; the only runs it may read, watch or stop | `sessions.*` bridge methods | Every run of the plugin's flow |
| **App path** (nav path) | The part of the URL after `/plugins/<id>`, e.g. `/conversations/c_…?page=2`; mirrored in the frame's `#fragment` | Deep links, `nav.changed`, `nav.navigate` | A path the frame navigates itself (the frame has hash routing only) |
| **Nav sync** | Keeping EpicStaff's URL and the app's screen in step: the app reports with `nav.changed`, the host pushes `nav.navigate` for Back/Forward and the address bar | Bridge v2, the SDK | The frame's own history (the SDK turns its `pushState` into `replaceState`) |
| **Theme tokens** | EpicStaff's colours and font as a public set of CSS variables (`--es-color-…`, `--es-font-family`) plus `dark` / `light`, sent at handshake and on every change | Bridge v2, the SDK | A UI kit; mandatory for apps |
| **UI session** | `POST /api/plugins/{id}/ui-session/`: returns the frontend URL (signed, or the dev URL), the bridge version and the resolved access list | Opening the host page | A login session |
| **Page token** | The signed, reusable, 12-hour token inside the frontend URL, re-checked on every file request | Loading frontend files | A credential for the API (it unlocks only the plugin's own files) |
| **Plugin asset** | One frontend file stored in the database (`PluginAsset`) | Serving the frontend; upgrade survival | A storage (RustFS) file — those are plugin resources of type storage file |

## Lifecycle

| Term | Means | Applies to | Is NOT |
|---|---|---|---|
| **Suspend** | Switch a plugin fully off, reversibly: no nav button, its flows cannot start by any route, its agents, tools and tables cannot be used by other flows | `POST …/suspend/` | Delete; or hiding only the frontend |
| **Needs attention** | Status when something blocks readiness, e.g. knowledge indexing failed; comes with a reason and a retry | Plugins tab | Suspended |

## Author tooling

| Term | Means | Applies to | Is NOT |
|---|---|---|---|
| **SDK** | `@epicstaff/plugin-sdk` (`plugin-sdk/`): the typed bridge client, nav sync, theme, storage stand-in, mock host ([[plugin-author-tooling]]) | Bridge-2 apps | Published on npm (it lives on the branch) |
| **CLI** | `epicstaff-plugin validate` / `pack`: checks a plugin folder like the server does and writes a reproducible zip | Authors | The authority — the server re-validates everything |
| **Mock host** | A fake EpicStaff host in the app's own page, with flows as functions and tables as arrays, used when the app is not framed | Standalone development | Loaded inside EpicStaff (production builds keep it as an unused lazy chunk) |
| **Storage stand-in** (storage shim) | In-memory `localStorage` / `sessionStorage` / `document.cookie` where the sandbox throws | Bridge-2 apps | Persistence (nothing survives a reload) |
| **Dev mode** | An instance-level switch (`PLUGINS_DEV_MODE`) that lets an admin load an installed plugin's frontend from a localhost dev server | Local dev stacks | Available in production |
| **Dev URL** | The `http://localhost…` / `http://127.0.0.1…` address an admin sets for a plugin; served only to that admin while dev mode is on | `POST/DELETE …/dev-ui/` | A URL other users see |
| **DEV banner** | The host's notice above a frontend loaded from a dev URL | Dev mode | Optional |

## Related

- [[plugins-prd]] — [Plugins — product requirements](plugins-prd.md)
- [[plugins-rules]] — [Plugins — rules](plugins-rules.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugin-bridge-v2]] — [Plugin bridge v2](plugin-bridge-v2.md)
- [[plugin-author-tooling]] — [Plugin author tooling: SDK, CLI, dev mode](plugin-author-tooling.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-code-map]] — [Plugins code map](code-map.md)
