---
id: plugins-rules
title: Plugins — rules
type: rules
status: draft
tags: [plugins, prototype, security, rbac]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-prd, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugins-api-contract, plugins-glossary]
---

# Plugins — rules

The invariants every change to Plugins must keep. Each rule says *what* must hold and *why*. The product reasoning is in
[[plugins-prd]]; where each rule is enforced is in [[plugins-architecture]].

## Security

| # | Rule | Why |
|---|---|---|
| S1 | **Plugin page code is untrusted.** Treat everything a plugin page does as possibly malicious. | Anyone can build a plugin file; there is no signature check in v1. |
| S2 | The page **never receives a token** and has **no network access**. It reaches EpicStaff only through the bridge ([[plugin-bridge-v1]]). | A page that holds a token can call any API as the user. |
| S3 | **Effective rights = the logged-in user's permissions ∩ the plugin's access list.** The host enforces the access list; the API enforces the user's permissions. | Neither the plugin nor the user can exceed what both allow. |
| S4 | The page names resources by **alias only**; ids come from the access list. Anything not on it is `forbidden`. | The page cannot guess its way to other flows. |
| S5 | A page may only read, watch or stop **runs it started itself** (tracked per open page). Others answer `not_found` before any request is sent. | Otherwise a plugin could read other users' chats with the same flow. |
| S6 | **Secret values never travel in the plugin file** — only slots (name + description). The admin types values at install. | Files get shared, posted and committed. |
| S7 | The install review shows **where each secret will be sent** (provider standard endpoint, or a custom host in a warning style). | A malicious plugin could point a config at its own server to collect the key. |
| S8 | The install warning is honest: *anything the page can see could be sent to the plugin's author.* | A sandboxed page can still navigate away with data; shutting it down afterwards is cleanup, not prevention. |
| S9 | Plugin-supplied text is rendered as text. The icon is shown only through `<img>` from a PNG/SVG data URL. Never `innerHTML` or `bypassSecurityTrust*` with plugin content. | Plugin strings would otherwise inject code into the trusted app. |
| S10 | Plugin files are served with `Content-Security-Policy: sandbox allow-scripts; default-src 'none'; … connect-src 'none' …`, `nosniff`, `no-store`, no cookies, from a **signed, expiring URL** that re-checks permission on every request. | The sandbox holds even if someone opens a file URL directly. |
| S11 | The iframe's `sandbox="allow-scripts"`, `referrerpolicy` and `allow` attributes are **static** in the template. | Bindings could widen the sandbox at runtime. |

## Install

| # | Rule | Why |
|---|---|---|
| I1 | Install is **all-or-nothing** — one database transaction; storage writes are cleaned up on failure. | A half-installed plugin cannot be suspended or deleted cleanly. |
| I2 | Installing needs `plugins:create` **and create permission on every resource type in the plugin**. A missing permission is reported before anything is written. | `plugins:create` alone must not become a way to create secrets, flows or configs the user cannot create. |
| I3 | Install **always creates new rows** (force-create); it never reuses the organization's existing ones. Only rows the install **created** are registered as plugin resources. | Otherwise suspend or delete would hit the organization's own configs and agents. |
| I4 | One install per plugin id per organization. *(Prototype: a second install answers 409 "already installed"; later this becomes update/downgrade/reinstall.)* | The plugin id is what updates will key on. |
| I5 | A plugin secret name or storage path already taken in the organization answers **409 `plugin_resource_conflict`**. | Never overwrite the organization's own secret or file. |
| I6 | The file is validated completely before install; every problem is reported at once (see [[plugin-package-format]]). | One fix-and-retry round, not one per error. |

## Lifecycle

| # | Rule | Why |
|---|---|---|
| L1 | Status is `preparing` → `ready`, or `needs_attention` with a reason; `suspended` is a **separate flag**, so resuming returns to the real state. | Suspension must not erase whether knowledge is ready. |
| L2 | **Suspended means fully off.** The check runs in `run_session` **before a session row is created** (manual, webhook, Telegram, schedule, subflow tool all pass there), covers subflows, and also blocks the plugin's agents and tools inside other flows. Live runs are stopped. | "Suspended" that still answers webhooks would surprise everyone. |
| L3 | A refused run answers **409 `plugin_suspended`**. | Clear, distinct error for clients. |
| L4 | **Delete** shows a preview first, needs **delete permission on every type it removes**, marks the plugin suspended first (nothing new can start mid-delete), then removes each resource through its owning service — including the run history of the plugin's flows. Rows the organization already deleted are skipped; a custom model the organization's own configs use is kept. | Symmetric with I2; never break the organization's own resources. |
| L5 | *(Deferred)* Update / downgrade / reinstall replaces resources in place and **keeps** secret values (matched by slot name), access-list narrowing and run history; the confirmation lists resources edited since install. | Predictable upgrades without a merge UI. |

## Permissions (RBAC)

| Action on `plugins` | Allows | Extra requirement |
|---|---|---|
| `read` | See the Plugins tab and plugin details | — |
| `create` | Inspect and install | create on every contained resource type |
| `update` | Suspend, resume, retry | re-entering secrets also needs `secrets:create` |
| `delete` | Delete preview and delete | delete on every removed resource type |
| `use` | Open plugin pages; get the navigation buttons (`GET /api/plugins/nav/`) | — |

- Built-in roles: **Org Admin** holds all five; **Member and Viewer hold none**. Admins grant use through custom roles.
- Every plugin endpoint is organization-scoped: another organization's plugin answers **404**, never 403. API keys are
  refused on these routes.

## Upgrade survival

| # | Rule | Why |
|---|---|---|
| U1 | Plugin page files are stored **in the database** (`PluginAsset`), never in a container image or container filesystem. | They must survive image rebuilds and upgrades, and are included in backups. |
| U2 | Plugin data lives in ordinary migrated tables; nothing at runtime depends on the original `resources.json` or the import format version. | Upgrades migrate it like any other data. |
| U3 | **Bridge v1 is frozen.** New behaviour goes into bridge v2; v1 semantics never change. A spec pins the v1 method table. | Pages built for v1 must keep working after EpicStaff changes. |
| U4 | Never rename the RBAC value `plugins` or its action bits. | They are stored in roles. |
| U5 | Plugin resources are linked through the plugin's **own type names**, not Django content types. A migration that recreates linked rows with new ids must remap the registry. | Model renames and app moves must not orphan plugins. |

## Rules for plugin authors

What a plugin page may and may not do inside the sandbox is listed in [[plugin-package-format]] → "Rules for plugin pages".

## Related

- [[plugins-prd]] — [Plugins — product requirements](plugins-prd.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-glossary]] — [Plugins glossary](plugins-glossary.md)
