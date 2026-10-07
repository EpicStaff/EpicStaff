---
id: plugins-prd
title: Plugins — product requirements
type: prd
status: draft
tags: [plugins, prototype]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-rules, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugin-bridge-v2, plugin-author-tooling, plugins-api-contract, plugins-glossary, plugins-code-map]
---

# Plugins — product requirements

> Prototype on branch `proto/plugins-06-10-26`. Never merged to `main`. Requirements were agreed in two structured
> interviews and explicitly confirmed by the product owner: plugins on 2026-10-06, plugin apps on 2026-10-07
> ([alignment summary](alignment-plugin-apps-2026-10-07.md)). This page describes the concept **as built at
> `bfeea626f`** — the baseline before the concept is reworked.

## Problem

EpicStaff can build flows, agents, tools and knowledge bases one by one, but it has no way to **ship a ready-made
capability as one unit**. Setting up a chat bot today means creating a flow, an agent, LLM and embedding configs,
secrets, a knowledge collection with its documents, and wiring them together by hand — and there is nowhere to give that
bot its own screen, let alone a whole admin app.

## The idea

A **plugin** is a mini-app that runs on EpicStaff. It has three parts:

| Part | What it is | Chat-bot example | Chat Admin example |
|---|---|---|---|
| **Backend** (its brain) | Ordinary EpicStaff building blocks it brings and installs into the organization: flows, agents, tools, knowledge, key-value tables, LLM and embedding configs, secret slots | The "Chat Bot" flow, its agent, the product docs as knowledge | The chat flow, its agent, and a `conversations` key-value table the flow writes every turn into |
| **Frontend** (its face) — *optional* | Its own UI in a sandboxed frame inside EpicStaff: either **one simple page** (bridge v1) or a **full app** built with any SPA framework, with its own screens, deep links and EpicStaff's theme (bridge v2) | One chat page | An Angular app: Chat, Conversations list (search, sort, paging), one conversation's transcript, About |
| **Access list** (the contract) | Exactly what the frontend may touch — always limited further by what the person using it may do | "Run flow *Chat Bot*, read its own runs" | The same for the flow, plus "read key-value table *conversations*" |

EpicStaff is the plugin's runtime and backend; the frontend is its face. A plugin can also have **no frontend at all** —
for example a Telegram support bot that is only a flow with a webhook trigger, an agent and knowledge, installed in one
step.

## Users

- **Org Admin** — installs, suspends, resumes and deletes plugins; types in secret values; decides who may use them;
  on a dev instance, points a plugin at a local dev server.
- **Org member with `plugins:use`** — opens a plugin's frontend from the navigation and uses it.
- **Plugin author** — builds the plugin file ([[plugin-package-format]]) with the SDK and CLI, and iterates against a
  real EpicStaff in dev mode ([[plugin-author-tooling]]).

## User journey

1. **Settings → Plugins → Add plugin.** A drag-and-drop popup takes the plugin file (`.zip`).
2. **Review.** EpicStaff shows what will be installed (including key-value tables), the access list in plain words, a
   warning that the plugin runs its own code, and one input per secret slot with **where that secret will be sent**.
3. **Install.** A progress bar, then "Plugin added successfully". Knowledge keeps indexing in the background:
   *Preparing knowledge…* → *Ready* (or *Needs attention* with a reason, a Secrets button to fix the key, and Retry).
4. **Use.** Members with access see a new button with the plugin's icon in the left navigation. It opens the plugin's
   frontend **inside EpicStaff's shell** at `/plugins/<id>/…`; the left bar stays. A plugin app's own screens get real
   URLs (`/plugins/7/conversations/c_…`) that survive a refresh and work with Back/Forward.
5. **Suspend / Resume / Delete** from the Plugins tab.
6. **Author loop (dev instances only).** Settings → Plugins → *Dev mode* → `http://localhost:4300/`: the installed
   plugin's app now loads live from the author's dev server, with real data, a DEV banner and live reload.

## Requirements (confirmed)

**What a plugin is**
1. *Internal* plugins only: a file uploaded to and hosted by EpicStaff. *External* plugins (running elsewhere, calling the
   API) are out of scope.
2. A plugin = ordinary EpicStaff resources + an optional frontend + a manifest with a stable **id and version**, name,
   icon, access list and secret slots.
3. A plugin is a **resource, not an identity**: it has no service account. Everything it installs belongs to the
   organization, stays **linked** to the plugin, and stays **editable**.
4. The plugin ships its **own LLM and embedding configs**; their API keys come from secret slots.

**Managing plugins**
5. The Plugins tab lives in Settings (Settings is a dialog in EpicStaff, so it is a new tab there).
6. Install is **all-or-nothing**: if anything fails, nothing is created.
7. Knowledge indexes **in the background** after install; the plugin shows its status and offers retry.
8. **Suspend** switches the plugin fully off (button hidden, its flows cannot start by any route, its agents, tools and
   tables cannot be used by other flows); **resume** restores it; no data is lost.
9. **Delete** removes everything the plugin installed — including edits, the run history of its flows and the rows of
   its tables — after a preview, and warns about the organization's own flows that reuse plugin parts.
10. The same plugin id again means **update / downgrade / reinstall**: replace in place, keep secret values, access-list
    narrowing and run history, and list the resources that were edited. *(Prototype: rejected with "already installed".)*

**Using plugins**
11. **RBAC:** a new `plugins` row in the permission table, role-level like Flows. Only Org Admin holds it by default.
12. Users with `plugins:use` see one navigation button per ready plugin, opening `/plugins/<id>`.
13. The frontend runs **isolated**: no token, no outside network, talks to EpicStaff only through the **bridge**, acting
    as the logged-in user and capped by the access list. Admins may narrow the access list, never widen it.

**Security**
14. Secret **values never travel in the file** — only empty slots with descriptions; the admin types the values.
15. No signature check in v1; only holders of the install permission can install, after seeing the full review.

**Upgrades**
16. Installed plugins **survive EpicStaff upgrades**: their resources, secrets, status, access list and frontend files
    persist, and the bridge is versioned so a frontend built for bridge v1 keeps working.

**Plugin apps** (confirmed 2026-10-07)
17. A plugin can ship a **real frontend application** built with any SPA framework that compiles to static files, with
    any component library, all bundled. The platform supports what production builds emit: ES modules, lazy-loaded
    chunks, web fonts, framework-injected styles. Still forbidden: `eval`, inline scripts, any outside network.
18. The app opens **inside EpicStaff's shell** from its left-bar icon, has its **own internal navigation**, and its deep
    links survive a refresh; Back/Forward move one app screen at a time.
19. A plugin can ship **key-value tables**. The access list gains a `key_value_table` type with one action, `read`. The
    app lists entries (key search, sort by key or last update, paging) and reads one entry's full value — mirroring
    EpicStaff's own REST API. Writing stays with the plugin's flows.
20. The app gets **nothing on the agent**: the agent is installed and used by the flow only.
21. EpicStaff passes its **theme** — design tokens as CSS variables plus dark/light mode — pushed live. Using it is
    optional; authors may bring their own look.
22. **No persistence** in the app: state lives in memory and in the URL. The SDK provides an in-memory
    `localStorage` / `sessionStorage` stand-in so libraries that touch storage do not crash.
23. **Author tooling:** an SDK (typed bridge client, storage stand-in, mock host), a CLI that validates and packs the
    plugin file, and a **guarded dev mode** that exists only when the EpicStaff instance itself runs in dev mode, is
    admin-only, applies to the admin who set it, and always shows a DEV banner.
24. Who can use an app is unchanged: the person must personally hold the underlying permissions (user ∩ access list).

The exact invariants behind these requirements are in [[plugins-rules]].

## Refinements agreed after the interviews

- Installing needs `plugins:create` **plus create permission on every resource type the plugin contains**; deleting needs
  delete on every type it removes. A plugin whose flows use key-value nodes also needs the table permissions those
  nodes' modes require.
- A sandboxed page can still leak what the bridge gives it (for example by navigating away with data in the URL); the
  install warning says so plainly.
- Python code that reads secrets by name is rejected in v1 (it would clash with the organization's own secret names).
- Install always creates new rows; it never reuses the organization's existing ones. Installed tables get the plugin
  prefix like secrets: `chat_admin__conversations`.
- A plugin flow may only use key-value tables **the plugin itself ships** — otherwise it could read the organization's
  own tables and hand the rows to its app.
- After the security reviews: a page can only read or stop the runs **it started itself**; the review shows where each
  secret is sent; plugin documents are refused when opened as a top-level page (a leaked link must not become a page on
  EpicStaff's own domain).

## Prototype scope

- **In:** the chat-bot example (bridge v1) and the Chat Admin example (bridge v2) end to end — Plugins tab, install
  with review and secret slots, background knowledge indexing, navigation button, sandboxed page/app talking to its
  flow and its table through the bridge, deep links, live theme, secret re-entry and retry, suspend, resume, delete
  with preview, dev mode, SDK and CLI.
- **Deferred:** update / downgrade / reinstall, the access-list narrowing UI, the edited-resources warning, a slug in
  the URL instead of the database id.

## Non-goals (v1)

External plugins · plugin signing · per-plugin grants (permissions are per role) · anything that runs with nobody logged
in (e.g. a public chat widget) · installing old plugin files on a newer EpicStaff · moving plugins between servers ·
writes to key-value tables from the app · querying inside table values · per-user persistent app storage · UI slots
inside EpicStaff's own screens · a published EpicStaff UI kit · outside network from the app.

## Open questions

1. **Secrets in the plugin app — UNRESOLVED.** Wanted: the app lists its own secret slots (names and set/missing,
   never values) and sets values, both through an EpicStaff-owned dialog (the value never enters plugin code) and
   through a plugin-handled `secrets.set` (plugin code sees the plaintext). How `secrets.set` is gated is undecided.
   Nothing is built.
2. **How much more EpicStaff data may a plugin use?** Today: run its own flows, watch the runs it started, read its own
   tables. Candidates: write its own tables, read its other resources, organization-wide data (would need a generic API
   proxy with per-endpoint checks).
3. **Per-plugin `use` grants** for operators who lack the underlying permissions — today plugin apps are in practice
   for admins and power users.
4. **UI slots inside existing screens** (a panel on the Flows page, a node in the flow editor).
5. Guard gaps: realtime agents and the scheduler are not blocked while a plugin is suspended; a suspended plugin's table
   is still readable through EpicStaff's own Key-Value Tables page.
6. **Safari:** on 2026-10-07 a plugin frame stayed white in Safari 26.4 (the page loaded, none of its files were
   requested), while Chrome and WebKit 26.6 render it. Cause not found yet.

## Related

- [[plugins-rules]] — [Plugins — rules](plugins-rules.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugin-bridge-v2]] — [Plugin bridge v2](plugin-bridge-v2.md)
- [[plugin-author-tooling]] — [Plugin author tooling: SDK, CLI, dev mode](plugin-author-tooling.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-glossary]] — [Plugins glossary](plugins-glossary.md)
- [[plugins-code-map]] — [Plugins code map](code-map.md)
