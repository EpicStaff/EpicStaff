---
id: alignment-plugin-apps
title: Plugin apps — alignment summary
type: alignment
status: confirmed
tags: [plugins, prototype, plugin-apps]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-prd, plugins-rules, plugin-bridge-v1, plugin-package-format]
---

# Plugin apps — alignment summary

> Agreed in a structured interview and explicitly confirmed by the product owner (Ihor Polishchuk) on 2026-10-07
> ("Yes" to the full restatement, including the items marked *proposal*). Extends [[plugins-prd]] open questions 1
> and 2 (how much data a plugin page may use; full-framework pages).

## Topic and goal

A plugin can ship a **real frontend application** — multi-screen, built with a framework, like EpicStaff itself —
instead of one simple page, and that application works with EpicStaff data through the bridge.

## Agreed understanding

**Worked example — "Chat Admin" plugin.** Ships the chat bot flow, its agent, and a **key-value table** the flow
stores conversations in. The plugin app lists conversations and opens transcripts. The flow writes the table; the app
only reads it.

**Placement.** One icon per plugin in EpicStaff's left bar opens the app **inside EpicStaff's shell** (bar stays, the
app fills the content area). The app has its own internal navigation; deep links such as
`/plugins/chat-admin/conversations/42` survive a refresh because the app and EpicStaff keep the URL in sync over the
bridge.

**Build.** Any SPA framework that builds to static files, and any components or UI libraries, all bundled. The
platform supports what production builds emit: ES modules, lazy-loaded chunks, web fonts, framework-injected styles.
Hard lines kept: no `eval` / inline scripts, **no outside network** — everything ships inside the plugin file.

**Theme.** EpicStaff passes its design tokens as CSS variables plus dark/light mode, pushed live. Using them is
optional.

**Access list (what the app can do).**

| Resource | Actions |
|---|---|
| The plugin's flow | run (as today) |
| The plugin's key-value table | read only — `kv.list` (key search, sort by key or updated-at, paging), `kv.get` (one row's full value); mirrors today's REST API |
| The plugin's agent | none — installed and used by the flow, never touched by the app |

**Who can use it.** Unchanged: the person must personally hold the underlying permissions (user ∩ access list).

**State.** No persistence. State lives in memory and in the URL; the SDK provides an in-memory
`localStorage` / `sessionStorage` stand-in so libraries that touch storage do not crash.

**Shipping key-value tables.** A key-value table becomes a portable export/import entity and a plugin resource type
with RBAC. Install always creates a new table (never reuses an org table); suspend and delete apply to it like every
other plugin resource; delete removes the table and its rows.

**Author tooling.**
- **SDK** — typed bridge client, the storage stand-in, a mock host.
- **CLI** — validates the manifest and packs the zip.
- **Dev mode** — an installed plugin's app loads live from the author's dev server (`localhost`) with hot reload, real
  data and the real bridge. It exists only when the EpicStaff instance itself runs in dev mode, is admin-only, and
  shows a visible "DEV" banner. Production never has the switch.

## Decisions made

| Question | Chosen | Rejected alternatives |
|---|---|---|
| What the app does with conversations | Read only | Read + manage (delete, tag, resolve); read + manage + operator takeover |
| App's reach to the agent | None | Read config; change config |
| Where the app opens | Inside EpicStaff's shell, own internal navigation, deep links | Full-screen takeover; separate browser tab |
| Allowed frameworks | Any SPA building to static files | Angular only |
| Theming | Optional tokens + dark/light | Plus a published UI kit; no theming |
| Author development loop | SDK + CLI + guarded dev mode | SDK + mock host + plugin update; docs only |
| Who can use a plugin app | Holders of the underlying permissions (unchanged) | `plugins: use` as the full grant, per plugin; admins only |
| Table reads | Mirror today's REST API | Querying inside JSON values |
| App state persistence | None in v1 (in-memory stand-in) | Per-user bridge storage; a KV table for app state |
| Where the work goes | Extend `proto/plugins-06-10-26` | New stacked prototype branch; production spec on `developer` |

**Implementation proposals, confirmed:**
- Sample app built in **Angular** (team stack; hardest sandbox case — lazy chunks, injected styles).
- The page link stays valid for as long as the app is open (no 10-minute expiry).
- UI size limits raised to fit a real build: about 300 files / 20 MB.
- New methods go into **bridge v2**; v1 stays frozen so the existing chat-bot page keeps working. The access list gains
  a `key_value_table` type.
- A plugin-installed table name carries the plugin prefix, like secrets (`chat_admin__conversations`), to avoid
  clashing with the org's own tables.
- The SDK lives on the branch, not published to npm.

## Out of scope

- Writes to the key-value table; querying inside values.
- Per-user persistent storage.
- UI slots inside EpicStaff's own screens.
- Outside network from the plugin app.
- A published EpicStaff UI kit.
- Per-plugin `use` grants for operators who lack the underlying permissions — **known limitation**: in practice plugin
  apps are for admins and power users.
- Plugin **update** — same id still returns 409; dev mode covers the author's iteration loop.

## Open / unresolved

- **Secrets in the plugin app — UNRESOLVED.** Wanted: the app lists the plugin's own secret slots (names and
  set/missing status, never values) and sets their values, both through an EpicStaff-owned dialog (the value never
  enters the plugin's code) and through plugin-handled `secrets.set` (the plugin's code sees the plaintext). How
  `secrets.set` is gated is undecided; the recommendation on the table was two separately declared actions per slot,
  with `set` flagged in the install review. **Nothing secrets-related is built until this is decided.**

## Confirmed by

Ihor Polishchuk (product owner), 2026-10-07 — explicit "Yes" to the full restatement.
