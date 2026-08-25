# Agents & Surfaces — Concept & Behavior (EST-2946)

Consolidated reference for the **Agents** feature on EpicStaff. This gathers the
decisions made across several iterations of the concept.

> **Scope of this doc:** the product concept and the intended behavior. Where the
> current code differs from the target, it is marked **(not built yet)**.
>
> **Backend status:** Agent Definitions and Surfaces are now wired to the real API
> (`/api/agent-definitions/`, `/api/surfaces/`). Key model facts:
> - A surface's **`owner_agent`** is its kind: **null = shared**, set = **agent-specific**
>   (owned by that one agent).
> - An agent's **`default_surfaces`** is the agent↔surface **assignment**: a list of
>   `{ surface, place }` (`place ∈ all | flow | chat`, where `all` = Every-Place). A
>   specific surface is always in its owner's `default_surfaces`; a shared surface is
>   there only where it's been assigned.
> - Surface tools/knowledge/files are real nested arrays (`python_tools`, `mcp_tools`,
>   `knowledge`, `storage_items`) plus `allow_creation`. The **Files** tab is wired to
>   real storage: `StorageItem.id` is the numeric `StorageFile` id (backend returns it),
>   and `storage_items[].storage_file` references it. Selected-file *names/paths* are
>   resolved via `GET /api/storage/files/?ids=1,2,3` when the card body is shown, so the
>   selected-files table renders as a folder tree; `File #<id>` remains only as a
>   fallback for ids the backend no longer knows.

---

## 1. What "Agents" are

**Agents** are a **new first-class entity** on EpicStaff. They are **not** the old
`staff` agents from the previous concept — do not conflate the two. The backend
model is `AgentDefinition` (`/api/agent-definitions/`).

An agent bundles:

- **Name**, **About this Agent** (backend field: `description`), **LLM** (`llm_config`).
- **Boot Instructions** (`instructions`) — see [§7](#7-boot-instructions).
- A set of **Surfaces** attached to it, each pinned to a **usage place**
  (Every-Place / Flow / Chat) — see [§3](#3-surfaces)–[§4](#4-usage-places).

---

## 2. The Agents navbar tab & explorer tree

Agents get their **own navbar tab**. The left side is a **VSCode-like explorer**
with one section per entity. The right side is a **preview/detail panel**.

**Sections present now:**

1. **AGENTS** — each agent expands to its docs + a **Surfaces** group.
2. **SHARED SURFACES** — flat list of all shared surfaces.
3. **STORAGE** — the file storage tree (reused from the Files feature).

**Planned to migrate into this tab later:** Tools, Knowledge Collections (Knowledge
Sources), etc. — and, in general, every project entity **except Flows themselves**.
Today it is only Agents, Shared Surfaces, and Storage.

Each section can be shown/hidden via the **"Branches (N)"** filter popup (AGENTS is
locked-on). Sections expand/collapse independently.

**Tree interaction rules (current):**

- A node row **click → opens its preview** in the right panel.
- **Expand/collapse is the chevron's job only** (agents and groups). Clicking the
  row never toggles expansion.
- Leaf nodes (a surface, an agent doc) → click opens preview.

---

## 3. Surfaces

A **Surface** is a reusable bundle of **tools + files + knowledge collections**
(with per-resource permissions). Backend model: `Surface` (`/api/surfaces/`).

### 3.1 Two kinds

| Kind | Meaning |
|------|---------|
| **Shared Surface** | Can be added to **any** agent. Being shared does **not** mean it is auto-added to every agent — it only means it is *available* to attach. |
| **Agent-Specific Surface** | Created for **one** agent. Lives only under that agent. |

### 3.2 Kind vs assignment (important)

Two separate relations:

- **Kind** is the surface's **`owner_agent`**: null = shared, set = agent-specific.
- **Assignment** is the agent's **`default_surfaces`** (`{ surface, place }` rows).

A **shared** surface can be **assigned** to agents (it appears in their
`default_surfaces`) and **stays shared** — assignment ≠ converting to specific. An
**agent-specific** surface is always assigned to its owner.

- **Assign a shared surface to an agent ("Add From Shared")** → add a
  `{ surface, place: all }` row to that agent's `default_surfaces`. The surface stays
  shared.
- **Detach** → remove the surface's row(s) from that agent's `default_surfaces`. (Only
  meaningful for shared surfaces — a specific surface stays assigned to its owner.)

### 3.3 Converting between kinds

- **Agent-Specific → Shared:** the surface's menu ("Make Shared") sets `owner_agent`
  to null. It stays in `default_surfaces` wherever it was assigned (so it remains
  visible under that agent) and is now available to all agents; others assign it later.
- **Shared → Agent-Specific: there is no in-place type change.** A shared surface
  cannot be "un-shared", because other agents/flows may rely on it. Instead the
  surface's menu offers **"Make Agent-Specific Copy"**: POST a **new** surface with
  `owner_agent = current agent`, copying the shared surface's bundle (tools /
  knowledge). The **original shared surface is left untouched**.

### 3.4 Where a surface shows in the tree

- Under an agent's **Surfaces** group: a surface appears **only if it is in that
  agent's `default_surfaces`** (a specific surface always is; a shared one only where
  assigned), grouped by `place`.
- Under **SHARED SURFACES**: every shared surface (`owner_agent == null`), always.

A shared surface is therefore visible in **two** places when assigned (under the
agent *and* under SHARED SURFACES). Only the link you opened it from is highlighted
(selection is keyed by surface **+ owning agent**, so the agent's copy and the
SHARED SURFACES copy never both highlight).

---

## 4. Usage places (where a surface is used inside an agent)

When a surface is assigned to an agent it has a **usage place** — the `place` of its
`default_surfaces` row:

- **Every-Place** — backend `all`; applies everywhere.
- **Flow** — backend `flow`; used in flows.
- **Chat** — backend `chat`; used in chats.

**Every-Place is open-ended:** beyond Flow and Chat, more usage places may be added
in the future. Treat the set as extensible.

In the agent's Surfaces panel the places are rendered as categories
(`every-place` / `flow` / `chat`). A surface can be **moved between places by
drag-and-drop** within the agent — this PATCHes the agent's `default_surfaces` row to
the new `place`.

---

## 5. Editing rules: read-only vs editable

The **same** shared surface is presented differently depending on where it is
opened:

- **Opened from an agent's tree** → **read-only**. You cannot edit it there. To make
  the read-only state actionable, the preview shows an **arrow ↗** that **navigates
  to the same surface under SHARED SURFACES** (revealing/expanding that section if it
  was hidden) and selects it there — **and there it is editable**.
- **Opened from SHARED SURFACES** → **editable**.
- **Agent-Specific surface opened from its agent** → **editable** (it has no other
  home).

### 5.1 Preview action icons (single-surface preview)

- **Shared, viewed from an agent (read-only):** **↗** (open in Shared Surfaces) +
  **✕** (detach from this agent — *not* delete).
- **Agent-Specific:** **🗑** (delete). No ↗ (it has no shared source).

### 5.2 Preview "…" menu (in the surfaces panel)

- **Agent-Specific surface (in an agent):** **Make Shared** + **Duplicate** (§6.1) +
  **Delete**.
- **Shared surface (in an agent):** **Make Agent-Specific Copy** (§3.3, §6.1) +
  **Detach from agent**. (No "Delete" — deleting a shared surface is done from SHARED
  SURFACES, and detach only removes the link to this agent.)
- **Shared surface (in SHARED SURFACES, editable):** **Duplicate** (§6.1, makes
  another shared, unattached) + **Delete**.
- **Agent:** **Duplicate Agent** (§6.1) + **Delete** (also import/export per §10).

---

## 6. Drag-and-drop

Decision (after going back and forth): **drag-and-drop only re-assigns /
re-attaches; it never changes a surface's type.**

- Drag a **shared** surface onto an **agent** → **attach** it to that agent (stays
  shared). It does **not** become agent-specific.
- Drag within an agent between **Every-Place / Flow / Chat** → change the **usage
  place**.
- **Type changes are never a drag operation** — they live in the "…" menu:
  Agent-Specific → Shared ("Make Shared"), and Shared → "Make Agent-Specific Copy"
  (a copy, not an in-place conversion — §3.3).

> An earlier proposal had "drag agent-specific surface into the Shared block ⇒ make
> it shared." That was **rejected** as inconsistent. Drag = assign only.

### 6.1 Duplicating agents and surfaces

Both agents and surfaces can be copied. The exact behavior depends on what is being
copied and where, because shared things must not be silently forked.

**Duplicate Agent — global only (in the AGENTS section).** Creates a new agent that
is a copy of the original (settings + surfaces) in the agents list. When copying:

- **Agent-specific surfaces are copied** (the new agent gets its own copies).
  ⚠️ *Not yet implemented:* the current `copy()` re-attaches the **same**
  `default_surfaces` to the new agent instead of forking the specific ones.
- **Shared surfaces are re-shared (attached) to the new agent**, **not** copied — the
  new agent links to the same shared surfaces.

(There is no per-flow "duplicate agent" — duplication lives in AGENTS.)

**Duplicating a surface — context-dependent:**

| Where | Surface kind | Action | Result |
|-------|--------------|--------|--------|
| Inside an agent | Agent-specific | **Duplicate** | Another agent-specific copy for that agent. |
| Inside an agent | Shared | **Make Agent-Specific Copy** (§3.3) | Independent agent-specific copy for that agent; shared original untouched. |
| In SHARED SURFACES (editable) | Shared | **Duplicate** | Another shared surface. **Not** auto-attached to the original's agents — the duplicate starts unattached. |

So a shared surface is **copied into a specific one** when you're inside an agent, and
**duplicated as another shared** when you're editing it in SHARED SURFACES (without
inheriting the original's attachments).

---

## 7. Boot Instructions

Boot Instructions (`instructions`) can be represented **two ways**:

- **Inline field** (textarea) for short content.
- **Separate `.md` file** when long. The UI nudges the user to "Create Markdown"
  past a length threshold.

**Tree representation:** `Boot_Instructions.md` appears as a node under the agent
**only** once the instructions are in markdown mode. Opening it shows a doc view with a
**Preview / Edit** toggle: Preview renders the markdown, Edit is a Monaco editor that
saves back to `instructions` on blur. (There is no `State.md` — the backend has no such
file.)

> The text is always stored in `instructions`; "markdown" is just a UI flag in
> `agent.metadata.instructions_format` (backend stores it but doesn't act on it). There
> is no real file — it's a file-like presentation.

---

## 8. Using surfaces / agents on a Flow or Chat (future)

A Flow (and likewise a Chat) can pull in capability at **three levels of
abstraction** — this is the key mental model:

1. **A single tool / file / knowledge collection** added directly.
2. **A Surface** — adds its whole bundle (tools + files + collections) at once.
3. **An Agent** — brings **all** of its surfaces along.
   3a. Everything inside an agent is essentially a set of **defaults** that ship with
   the agent — but on the flow where the agent is added you can **remove** them and
   **add** new ones. The agent's surfaces are a starting point, not a fixed set
   (see §8.3).

### 8.1 The Flow/Chat configuration has two fields

1. **Agent picker** — choose an agent. The agent's surfaces (with their already-defined
   permission sets) come along as **defaults** (see §8.3). On the flow you may
   **toggle those permissions on/off**, **remove** surfaces that came with the agent,
   and **add** new ones — i.e. you can change the agent's attached surfaces locally,
   **on the flow**.
2. **Add Surfaces** — beyond the agent's own surfaces, add **shared** surfaces, add
   surfaces **modified specifically for this flow** (custom-on-flow), or create
   custom ones.

So the effective set on a flow = **the agent's default surfaces (as edited here)** +
**extra surfaces (shared and/or flow-specific modified)**.

> **Scope of the edit:** changing an agent's surfaces *on a flow* affects **that
> flow only** — it does not mutate the agent definition. The agent keeps shipping the
> same defaults to the next place it is added.

### 8.2 Direct (agentless) usage

A surface may also be used **directly on a Flow or Chat, not through an agent**.
Those custom/flow-specific surfaces should be recorded **separately** under the
**Flow** group (and Chat group) — see §9. That grouping should show both the places
where the **agent** is used and the places where the surface is **used directly**.

> This whole section is **future functionality**. In the Surface Usage modal today
> the **Flow** and **Chat** blocks are present but **empty** (placeholders).

### 8.3 "Default agent surface" — terminology, not an entity

There is **no separate `default agent surface` entity**. "Default" is just **how we
refer to the set of surfaces that ships with an agent**: when you add an agent to a
flow, its attached surfaces arrive as the **defaults**, and you can then remove / add
/ adjust them on that flow (§8.1). There is no "non-default agent surface" concept —
everything inside an agent is simply its defaults.

Conceptually this *is* what an agent's default surfaces are — the bundle it brings by
default. The backend models this as **`default_surfaces`** (`{ surface, place }` rows),
which is exactly the per-place assignment described in §3.2.

---

## 9. Surface Usage modal ("Used by N")

The single-surface preview header has a **"Used by N →"** link opening a **Surface
Usage** modal. Contents:

- **Summary** — counts: `N agents` / `N flows` / `N chats`.
- **Agent** block — every agent the surface is attached to, each with its **usage
  place** label (Every-Place / Flow / Chat / future). Each row has an **↗** to jump
  to that agent.
- **Flow** block — direct (agentless) flow usage. **Empty placeholder for now.**
- **Chat** block — direct (agentless) chat usage. **Empty placeholder for now.**

**Status:** built. Agent usage is real (derived from attachment); place is
`Every-Place` for all rows until per-place tracking lands. Flows/chats are empty.

> Note: the same **View Summary** idea also appears per usage *place* — see §10.

---

## 10. Agent & surface lifecycle actions

- **Agents:** **import / export / delete / duplicate**, **individually or all**.
  Duplicate is built: it client-side clones the agent's fields with a new name and
  re-attaches the **same** `default_surfaces` (it does not yet create independent copies
  of the agent's specific surfaces — see §6.1). Import/export not built yet.
- **Deleting a surface:** must **warn that it is used somewhere** before deleting
  (it may be attached to agents / used on flows or chats).
- **View Summary:** per usage place inside an agent (Flow, Chat) you can open **View
  Summary** = the **aggregate of all surfaces of that kind** for the agent (e.g. all
  Every-Place + all Flow surfaces combined). `showViewSummary` is enabled for Flow
  and Chat. Aggregation is wired: it POSTs the place's surface ids to
  `/api/surfaces/combine/` and renders the merged bundle in a read-only summary dialog.
- **Autosave (agent):** a nameless agent is meaningless, so **creation happens only
  on blur of the Name field** (when non-empty); after the agent exists, any field
  edit autosaves.
- **Surface create:** wired to the real API — a draft surface is POSTed to
  `/api/surfaces/` on the name blur (`owner_agent` null for a shared surface, or the
  agent id for an agent-specific one). The created surface appears in the tree.
