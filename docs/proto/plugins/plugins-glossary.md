---
id: plugins-glossary
title: Plugins glossary
type: glossary
status: draft
tags: [plugins, prototype, terms]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-prd, plugins-rules, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugins-api-contract]
---

# Plugins glossary

Precise meanings for the words used across the Plugins docs ([[plugins-prd]], [[plugins-architecture]]).

| Term | Means | Applies to | Is NOT |
|---|---|---|---|
| **Plugin** | A mini-app installed into one organization: EpicStaff resources (its backend) + an optional page (its frontend) + an access list (the contract between them) | The `Plugin` row and everything linked to it | An identity or service account; a code extension of EpicStaff itself |
| **Internal plugin** | A plugin whose file is uploaded to and hosted by EpicStaff | Everything in this prototype | A statement about who wrote it (authorship is not checked in v1) |
| **External plugin** | A plugin that runs on its own servers and calls the EpicStaff API | Future work | Supported today |
| **Plugin file** (package) | The `.zip` an admin installs: `plugin.json`, `resources.json`, `knowledge/`, `files/`, `ui/` ([[plugin-package-format]]) | Install and inspect | A plain EpicStaff export file (that is only `resources.json`) |
| **Manifest** | `plugin.json` — identity, versions, secret slots and bindings, knowledge, storage files, access list, page entry | Validation at inspect/install | Where resources are defined (that is `resources.json`) |
| **Plugin id** | The stable `id` in the manifest, e.g. `chat-bot`; one install per organization | Duplicate detection; future updates | The database id used in API URLs (`/api/plugins/{id}/` takes the database id) |
| **Plugin resource** | A row the plugin's install **created**, recorded in the `PluginResource` registry with the plugin's own type name | Suspend, delete, status checks | A resource the organization already had (install never reuses those) |
| **Force-create** | Import mode that always creates new rows for plugin-owned types instead of reusing matching ones | Install | The importer's default behaviour |
| **Access list** | The manifest's `access[]`: which flows the page may touch, under which aliases, with which actions | The bridge's access policy | A permission grant to users (user permissions come from roles) |
| **Alias** | The name a page uses for a resource on its access list, e.g. `chat` | Every bridge call | A database id (the page never sees or sends ids for flows) |
| **Secret slot** | A named, described placeholder for a secret the admin types at install; stored as an organization secret `<PLUGIN>__<SLOT>` | Install, the Secrets dialog | A secret value inside the file (never allowed) |
| **Secret binding** | Manifest instruction putting a slot's secret into a field of a shipped config, e.g. `LLMConfig.api_key_secret` | Install | A lookup by secret name in code (rejected in v1) |
| **Secret destination** | Where a slot's value will be sent: a provider's standard endpoint or a custom host | Install review, Secrets dialog | A guarantee about the remote service |
| **Plugin page** | The plugin's own UI, served from its `ui/` files into a sandboxed iframe at `/plugins/<id>` | Users with `plugins:use` | Part of the EpicStaff app's code, or trusted |
| **Host** | The EpicStaff app around the plugin page; it owns the bridge, enforces the access list, and calls the API as the user | Every bridge call | A server component |
| **Bridge** | The postMessage + MessagePort protocol between page and host; versioned, v1 frozen ([[plugin-bridge-v1]]) | Page ↔ host | An HTTP API the page calls directly |
| **Page-scoped session** | A run the open page started via `flows.run`; the only runs it may read, watch or stop | `sessions.*` bridge methods | Every run of the plugin's flow |
| **UI session** | `POST /api/plugins/{id}/ui-session/`: returns a signed page URL, the bridge version and the resolved access list | Opening the host page | A login session |
| **Page token** | The signed, reusable, 10-minute token inside the page URL, re-checked on every file request | Loading page files | A credential for the API (it unlocks only the plugin's own files) |
| **Plugin asset** | One page file stored in the database (`PluginAsset`) | Serving the page; upgrade survival | A storage (RustFS) file — those are plugin resources of type storage file |
| **Suspend** | Switch a plugin fully off, reversibly: no nav button, its flows cannot start by any route, its agents and tools cannot be used | `POST …/suspend/` | Delete; or hiding only the page |
| **Needs attention** | Status when something blocks readiness, e.g. knowledge indexing failed; comes with a reason and a retry | Plugins tab | Suspended |

## Related

- [[plugins-prd]] — [Plugins — product requirements](plugins-prd.md)
- [[plugins-rules]] — [Plugins — rules](plugins-rules.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
