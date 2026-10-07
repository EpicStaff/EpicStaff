---
id: plugins-rules
title: Plugins — rules
type: rules
status: draft
tags: [plugins, prototype, security, rbac]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-prd, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugin-bridge-v2, plugin-author-tooling, plugins-api-contract, plugins-glossary, plugins-code-map]
---

# Plugins — rules

The invariants every change to Plugins must keep. Each rule says *what* must hold and *why*. The product reasoning is in
[[plugins-prd]]; where each rule is enforced is in [[plugins-architecture]] and [[plugins-code-map]].

## Security

| # | Rule | Why |
|---|---|---|
| S1 | **Plugin frontend code is untrusted.** Treat everything a plugin page or app does as possibly malicious. | Anyone can build a plugin file; there is no signature check in v1. |
| S2 | The frontend **never receives a token** and has **no network access**. It reaches EpicStaff only through the bridge ([[plugin-bridge-v1]], [[plugin-bridge-v2]]). | A page that holds a token can call any API as the user. |
| S3 | **Effective rights = the logged-in user's permissions ∩ the plugin's access list.** The host enforces the access list; the API enforces the user's permissions. | Neither the plugin nor the user can exceed what both allow. |
| S4 | The frontend names resources by **alias only**; ids come from the access list and **never reach the page** (`kv.*` results are stripped of entry and table ids). Anything not on the list is `forbidden`. | The page cannot guess its way to other flows or tables. |
| S5 | A page may only read, watch or stop **runs it started itself** (tracked per open page). Others answer `not_found` before any request is sent. | Otherwise a plugin could read other users' chats with the same flow. |
| S6 | **Secret values never travel in the plugin file** — only slots (name + description). The admin types values at install. | Files get shared, posted and committed. |
| S7 | The install review shows **where each secret will be sent** (provider standard endpoint, or a custom host in a warning style). | A malicious plugin could point a config at its own server to collect the key. |
| S8 | The install warning is honest: *anything the page can see could be sent to the plugin's author.* | A sandboxed page can still navigate away with data; shutting it down afterwards is cleanup, not prevention. |
| S9 | Plugin-supplied text is rendered as text. The icon is shown only through `<img>` from a PNG/SVG data URL. Never `innerHTML` or `bypassSecurityTrust*` with plugin content. | Plugin strings would otherwise inject code into the trusted app. |
| S10 | Plugin files are served with `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; … connect-src 'none' …; frame-ancestors 'self'`, `nosniff`, `no-store`, `Access-Control-Allow-Origin: *`, no cookies, from a **signed, expiring URL** (12 h) that re-checks permission on every request. | The sandbox holds even if someone opens a file URL directly. `ACAO *` only lets the opaque-origin page load its own modules and fonts; nothing served is credentialed — the token is the protection. |
| S11 | The iframe's `sandbox="allow-scripts"`, `referrerpolicy` and `allow` attributes are **static** in the template. Only `src` is set from code, and only after validation. | Bindings could widen the sandbox at runtime. |
| S12 | A plugin **document** (`.html`, `.svg`) is served only into a frame: a top-level navigation, or a document request without Fetch Metadata, answers an empty 404. | A leaked page link would otherwise open as a page on EpicStaff's own domain (a fake sign-in, say) for as long as its token lives. |
| S13 | A plugin's flows may only use key-value tables **the plugin ships**. A bundled key-value node naming any other table rejects the file. | By-name binding would let a plugin flow read the organization's own tables and return the rows to its app. |
| S14 | `kv.get` is **pinned to the granted table**: the host looks the key up in that table only and re-checks that the returned entry's table and key match before answering. | An entry id from elsewhere must never be readable through the app. |
| S15 | Navigation paths from the page are validated against a strict grammar (no `.`/`..`, no scheme, ≤ 1024 chars) before they reach EpicStaff's router; while the user is navigating the host, the page's `nav.changed` is ignored. | The page cannot steer EpicStaff outside `/plugins/<id>/…` or trap the user on a screen. |

## Install

| # | Rule | Why |
|---|---|---|
| I1 | Install is **all-or-nothing** — one database transaction; storage writes are cleaned up on failure. | A half-installed plugin cannot be suspended or deleted cleanly. |
| I2 | Installing needs `plugins:create` **and create permission on every resource type in the plugin**, plus the key-value table permissions each bundled key-value node's mode needs (read → `read`, write → `create` + `update`, delete → `read` + `delete`). A missing permission is reported before anything is written. | `plugins:create` alone must not become a way to create secrets, flows, tables or configs the user cannot create; a key-value node without its permission would import silently unbound. |
| I3 | Install **always creates new rows** (force-create); it never reuses the organization's existing ones. Only rows the install **created** are registered as plugin resources. | Otherwise suspend or delete would hit the organization's own configs, agents and tables. |
| I4 | One install per plugin id per organization. *(Prototype: a second install answers 409 "already installed"; later this becomes update/downgrade/reinstall.)* | The plugin id is what updates will key on. |
| I5 | Installed secrets and tables carry the plugin prefix (`CHAT_ADMIN__OPENAI_API_KEY`, `chat_admin__conversations`). A name or storage path already taken in the organization (tables compared case-insensitively) answers **409 `plugin_resource_conflict`**. | Never overwrite or share the organization's own secret, table or file. |
| I6 | The file is validated completely before install; every problem is reported at once (see [[plugin-package-format]]). | One fix-and-retry round, not one per error. |
| I7 | A `key_value_table` access entry needs **bridge 2**; each access type allows only its own actions (`flow`: `run`, `sessions.read`, `sessions.stop`; `key_value_table`: `read`). | A v1 page has no method that reads a table, so such a grant would be unusable. |

## Lifecycle

| # | Rule | Why |
|---|---|---|
| L1 | Status is `preparing` → `ready`, or `needs_attention` with a reason; `suspended` is a **separate flag**, so resuming returns to the real state. | Suspension must not erase whether knowledge is ready. |
| L2 | **Suspended means fully off.** The check runs in `run_session` **before a session row is created** (manual, webhook, Telegram, schedule, subflow tool all pass there), covers subflows, and also blocks the plugin's agents, tools and key-value tables inside the organization's own flows. Live runs are stopped. | "Suspended" that still answers webhooks would surprise everyone. |
| L3 | A refused run answers **409 `plugin_suspended`**. | Clear, distinct error for clients. |
| L4 | **Delete** shows a preview first, needs **delete permission on every type it removes**, marks the plugin suspended first (nothing new can start mid-delete), then removes each resource through its owning service — including the run history of the plugin's flows and the rows of its tables. Rows the organization already deleted are skipped; a custom model the organization's own configs use is kept. | Symmetric with I2; never break the organization's own resources. |
| L5 | *(Deferred)* Update / downgrade / reinstall replaces resources in place and **keeps** secret values (matched by slot name), access-list narrowing and run history; the confirmation lists resources edited since install. | Predictable upgrades without a merge UI. |

## Dev mode

| # | Rule | Why |
|---|---|---|
| D1 | Dev mode exists only when the instance runs with `PLUGINS_DEV_MODE=True`. Compose demands an explicit value (`${PLUGINS_DEV_MODE:?}`); production keeps it `False`. | The switch must not exist on a production instance at all. |
| D2 | Setting a dev URL needs `plugins:update`, and the URL must be plain `http://` on `localhost` or `127.0.0.1` (optional port and path; no userinfo, query or fragment). | The dev page gets the bridge with an admin's rights; it must come from the admin's own machine. |
| D3 | The dev URL applies **only to the admin who set it**; everyone else keeps the installed page. Clearing it is allowed even with the flag off. | One author's experiment must not change what colleagues see; a leftover URL must be removable. |
| D4 | The host shows a **DEV banner** while a dev URL is in use, and re-handshakes when a reloaded dev page sends a new `ready`. Production ignores a second `ready` and tears down on a second frame load. | The admin must always know the page is not the installed one; live reload must not need a manual refresh. |

## Permissions (RBAC)

| Action on `plugins` | Allows | Extra requirement |
|---|---|---|
| `read` | See the Plugins tab and plugin details | — |
| `create` | Inspect and install | create on every contained resource type (+ key-value node mode permissions) |
| `update` | Suspend, resume, retry, set or clear the dev URL | re-entering secrets also needs `secrets:create` |
| `delete` | Delete preview and delete | delete on every removed resource type |
| `use` | Open plugin frontends; get the navigation buttons (`GET /api/plugins/nav/`) | the bridge's calls still need the user's own permissions |

- Built-in roles: **Org Admin** holds all five; **Member and Viewer hold none**. Admins grant use through custom roles.
- Every plugin endpoint is organization-scoped: another organization's plugin answers **404**, never 403. API keys are
  refused on these routes.

## Upgrade survival

| # | Rule | Why |
|---|---|---|
| U1 | Plugin frontend files are stored **in the database** (`PluginAsset`), never in a container image or container filesystem. | They must survive image rebuilds and upgrades, and are included in backups. |
| U2 | Plugin data lives in ordinary migrated tables; nothing at runtime depends on the original `resources.json` or the import format version (the `KeyValueTable` export entity was added without raising it — older servers ignore it). | Upgrades migrate it like any other data. |
| U3 | **Every shipped bridge version is frozen.** New behaviour goes into a new version (v2 added `kv.*`, `nav.*`, `theme.changed`); a version's semantics never change once shipped. A contract spec pins each version's method table. | Frontends built for an older bridge must keep working after EpicStaff changes. |
| U4 | Never rename the RBAC value `plugins` or its action bits. | They are stored in roles. |
| U5 | Plugin resources are linked through the plugin's **own type names**, not Django content types. A migration that recreates linked rows with new ids must remap the registry. | Model renames and app moves must not orphan plugins. |
| U6 | Theme token names (`--es-…`) are a public set: **add, never rename or remove**. | Apps style themselves with them. |

## Rules for plugin authors

What a plugin frontend may and may not do inside the sandbox is listed in [[plugin-package-format]] → "Rules for plugin
frontends"; how to build and test one is in [[plugin-author-tooling]].

## Related

- [[plugins-prd]] — [Plugins — product requirements](plugins-prd.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugin-bridge-v2]] — [Plugin bridge v2](plugin-bridge-v2.md)
- [[plugin-author-tooling]] — [Plugin author tooling: SDK, CLI, dev mode](plugin-author-tooling.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-glossary]] — [Plugins glossary](plugins-glossary.md)
- [[plugins-code-map]] — [Plugins code map](code-map.md)
