---
id: plugins-prd
title: Plugins — product requirements
type: prd
status: draft
tags: [plugins, prototype]
created: 2026-10-07
updated: 2026-10-07
related: [plugins-rules, plugins-architecture, plugin-package-format, plugin-bridge-v1, plugins-api-contract, plugins-glossary]
---

# Plugins — product requirements

> Prototype on branch `proto/plugins-06-10-26`. Never merged to `main`. Requirements were agreed in a structured
> interview and explicitly confirmed by the product owner on 2026-10-06.

## Problem

EpicStaff can build flows, agents, tools and knowledge bases one by one, but it has no way to **ship a ready-made
capability as one unit**. Setting up a chat bot today means creating a flow, an agent, LLM and embedding configs,
secrets, a knowledge collection with its documents, and wiring them together by hand — and there is nowhere to give that
bot its own screen.

## The idea

A **plugin** is a mini-app that runs on EpicStaff. It has three parts:

| Part | What it is | Chat-bot example |
|---|---|---|
| **Backend** (its brain) | Ordinary EpicStaff building blocks it brings and installs into the organization: flows, agents, tools, knowledge, LLM and embedding configs, secret slots | The "Chat Bot" flow, its agent, the product docs as knowledge |
| **Frontend** (its face) — *optional* | Its own page, shown in a sandboxed frame inside EpicStaff, built with any web tooling | The chat page |
| **Access list** (the contract) | Exactly what the page may touch — always limited further by what the person using it may do | "Run flow *Chat Bot*, read its own runs" |

EpicStaff is the plugin's runtime and backend; the page is its face. A plugin can also have **no page at all** — for
example a Telegram support bot that is only a flow with a webhook trigger, an agent and knowledge, installed in one step.

## Users

- **Org Admin** — installs, suspends, resumes and deletes plugins; types in secret values; decides who may use them.
- **Org member with `plugins:use`** — opens a plugin's page from the navigation and uses it.
- **Plugin author** — builds the plugin file (see [[plugin-package-format]]).

## User journey

1. **Settings → Plugins → Add plugin.** A drag-and-drop popup takes the plugin file (`.zip`).
2. **Review.** EpicStaff shows what will be installed, the access list in plain words, a warning that the plugin runs its
   own code, and one input per secret slot with **where that secret will be sent**.
3. **Install.** A progress bar, then "Plugin added successfully". Knowledge keeps indexing in the background:
   *Preparing knowledge…* → *Ready* (or *Needs attention* with a reason, a Secrets button to fix the key, and Retry).
4. **Use.** Members with access see a new button with the plugin's icon in the left navigation; it opens the plugin page.
5. **Suspend / Resume / Delete** from the Plugins tab.

## Requirements (confirmed)

**What a plugin is**
1. *Internal* plugins only: a file uploaded to and hosted by EpicStaff. *External* plugins (running elsewhere, calling the
   API) are out of scope.
2. A plugin = ordinary EpicStaff resources + an optional custom page + a manifest with a stable **id and version**, name,
   icon, access list and secret slots.
3. A plugin is a **resource, not an identity**: it has no service account. Everything it installs belongs to the
   organization, stays **linked** to the plugin, and stays **editable**.
4. The plugin ships its **own LLM and embedding configs**; their API keys come from secret slots.

**Managing plugins**
5. The Plugins tab lives in Settings (Settings is a dialog in EpicStaff, so it is a new tab there).
6. Install is **all-or-nothing**: if anything fails, nothing is created.
7. Knowledge indexes **in the background** after install; the plugin shows its status and offers retry.
8. **Suspend** switches the plugin fully off (button hidden, its flows cannot start by any route, its agents and tools
   cannot be used); **resume** restores it; no data is lost.
9. **Delete** removes everything the plugin installed — including edits and the run history of its flows — after a
   preview, and warns about the organization's own flows that reuse plugin parts.
10. The same plugin id again means **update / downgrade / reinstall**: replace in place, keep secret values, access-list
    narrowing and run history, and list the resources that were edited. *(Prototype: rejected with "already installed".)*

**Using plugins**
11. **RBAC:** a new `plugins` row in the permission table, role-level like Flows. Only Org Admin holds it by default.
12. Users with `plugins:use` see one navigation button per ready plugin, opening `/plugins/<id>`.
13. The page runs **isolated**: no token, no outside network, talks to EpicStaff only through the **bridge**, acting as the
    logged-in user and capped by the access list. Admins may narrow the access list, never widen it.

**Security**
14. Secret **values never travel in the file** — only empty slots with descriptions; the admin types the values.
15. No signature check in v1; only holders of the install permission can install, after seeing the full review.

**Upgrades**
16. Installed plugins **survive EpicStaff upgrades**: their resources, secrets, status, access list and page files persist,
    and the bridge is versioned so a page built for bridge v1 keeps working.

The exact invariants behind these requirements are in [[plugins-rules]].

## Refinements agreed after the interview

- Installing needs `plugins:create` **plus create permission on every resource type the plugin contains**; deleting needs
  delete on every type it removes.
- A sandboxed page can still leak what the bridge gives it (for example by navigating away with data in the URL); the
  install warning says so plainly.
- Python code that reads secrets by name is rejected in v1 (it would clash with the organization's own secret names).
- Install always creates new rows; it never reuses the organization's existing ones.
- After the security review: a page can only read or stop the runs **it started itself**, and the review shows where each
  secret is sent.

## Prototype scope

- **In:** the chat-bot example end to end — Plugins tab, install with review and secret slots, background knowledge
  indexing, navigation button, sandboxed page chatting with its flow through the bridge, secret re-entry and retry,
  suspend, resume, delete with preview.
- **Deferred:** update / downgrade / reinstall, the access-list narrowing UI, the edited-resources warning.

## Non-goals (v1)

External plugins · plugin signing · per-plugin grants (permissions are per role) · anything that runs with nobody logged
in (e.g. a public chat widget) · installing old plugin files on a newer EpicStaff · moving plugins between servers.

## Open questions

1. **How much EpicStaff data may a plugin page use?** Today: run its own flows and watch the runs it started. Candidates:
   read its own resources, read organization-wide data, change organization-wide data (which would need a generic API
   proxy with per-endpoint checks).
2. **Full-framework pages** (for example an existing Angular app wrapped as a plugin) need platform changes: allow ES
   modules and web fonts (CORS header on plugin files), allow framework-injected styles, raise the 50-file / 5 MB limit,
   and keep page links valid longer than 10 minutes for lazy-loaded code.
3. **Theming** — pass EpicStaff's colours, fonts and dark/light mode to plugin pages.
4. **UI slots inside existing screens** (a panel on the Flows page, a node in the flow editor).
5. Guard gaps: realtime agents and the scheduler are not blocked while a plugin is suspended.

## Related

- [[plugins-rules]] — [Plugins — rules](plugins-rules.md)
- [[plugins-architecture]] — [Plugins — architecture](plugins-architecture.md)
- [[plugin-package-format]] — [Plugin package format](plugin-package-format.md)
- [[plugin-bridge-v1]] — [Plugin bridge v1](plugin-bridge-v1.md)
- [[plugins-api-contract]] — [Plugins API contract](api-contract.md)
- [[plugins-glossary]] — [Plugins glossary](plugins-glossary.md)
