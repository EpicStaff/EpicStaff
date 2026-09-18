# MCP Tools User Guide

This guide explains how to connect an external **MCP (Model Context Protocol)**
tool to EpicStaff and make it available to an agent.

MCP is an open protocol that lets an AI agent call tools hosted by an external
server — a GitHub integration, a search API, an internal service, and so on.
EpicStaff connects to remote MCP servers over HTTP/SSE.

---

## The one thing to understand first

**One MCP tool entry in EpicStaff = one single tool on one server.** It is not a
server connection.

Each entry stores both the server URL *and* the name of one specific tool on
that server. If your MCP server exposes three tools you want to use, you create
**three** entries, each repeating the same server URL with a different tool name.

Example — a server at `https://mcp.example.com/sse` exposing `search_issues`,
`create_issue`, and `add_comment`:

| Name (your label)      | Transport (server URL)          | Tool Name        |
| ---------------------- | ------------------------------- | ---------------- |
| GitHub — Search Issues | `https://mcp.example.com/sse`   | `search_issues`  |
| GitHub — Create Issue  | `https://mcp.example.com/sse`   | `create_issue`   |
| GitHub — Add Comment   | `https://mcp.example.com/sse`   | `add_comment`    |

The **Tool Name** must match the tool's name on the server exactly. EpicStaff
does not read the list of available tools from the server for you, so you need
this name from the server's own documentation.

---

## Overview of the process

Connecting an MCP tool takes three steps, in this order:

1. **Register the tool** in the org-wide tool catalog (Tools → MCP).
2. **Grant it to an agent** by adding it to a Surface (a named group of
   permissions).
3. **Use it in a flow** by attaching that Surface to an Agent or Task node on
   the canvas.

Steps 2 and 3 both go through Surfaces — that is the only way an agent gains
access to a tool.

If your MCP server requires authentication, do the optional step below first.

---

## Step 0 (optional): Create the auth secret

If the MCP server requires a token, create the secret **before** creating the
tool — the tool form only lets you pick from existing secrets, it cannot create
one.

1. Go to the **Settings** → **Secrets** tab.
2. Create a new secret and paste the token as its value.
3. Give it a recognisable name, for example `github-mcp-token`.

Secrets are stored encrypted and are scoped to your organization. Once saved,
the value cannot be read back in the UI — only replaced.

Skip this step for public or unauthenticated MCP servers.

---

## Step 1: Register the MCP tool

1. Open **Tools** from the main navigation.
2. Switch to the **MCP** tab.
3. Click **Create Tool** in the top right. The **Add MCP Tool** dialog opens.
4. Fill in the form:

   | Field                      | Required | What to enter                                                                                 |
   | -------------------------- | -------- | --------------------------------------------------------------------------------------------- |
   | **Name**                   | Yes      | Your own label for this entry, unique within the organization. Not sent to the server.        |
   | **Transport**              | Yes      | The MCP server's URL, e.g. `https://mcp-server.example.com/sse`.                              |
   | **Tool Name**              | Yes      | The exact tool name as registered on the MCP server.                                          |
   | **Timeout (seconds)**      | No       | How long to wait for a tool call to return. Defaults to `30`.                                 |
   | **Auth**                   | No       | The stored secret used to authenticate. Leave empty for unauthenticated servers.               |
   | **Init Timeout (seconds)** | No       | How long to wait for the initial connection handshake. Defaults to `10`.                      |

   **Name** is checked for uniqueness as you type — if you see *"A tool with
   this name already exists"*, pick a different label.

5. Click **Create**.

On success a confirmation appears and the tool shows up as a card in the MCP
list. From the card you can later edit it (click the card), duplicate it,
apply labels, export it, see where it is used, or delete it.

> **Saving does not test the connection.** EpicStaff stores what you typed
> without contacting the server, so a wrong URL, a wrong tool name, or an
> invalid token all save successfully. The problem only appears when an agent
> tries to use the tool. See [If something doesn't work](#if-something-doesnt-work).

To register several tools from the same server, use the card's **Duplicate**
action and change only the **Tool Name** each time.

---

## Step 2: Grant the tool to an agent

A registered tool sits in the catalog and does nothing until an agent is given
access to it. Access is granted through a **Surface** — a named group of
permissions (tools, files, and knowledge collections).

### Agent-specific vs. shared surfaces

Open **Agents** from the main navigation. The explorer on the left side of the
page has two sections that matter here:

- **Agents** — expand an agent to see the surfaces that belong to that agent
  alone. These are *agent-specific*: created inside the agent, editable there,
  and not offered to other agents.
- **Shared Surfaces** — surfaces that any agent can attach. Define a permission
  set once here and reuse it across many agents.

Which one to use:

- The tool is only for this one agent → create an **agent-specific** surface.
- Several agents need the same tool → put it in a **shared** surface once.

### The four surface places

Select an agent to open its detail view. Its surfaces are grouped into four
categories, and each is configured **independently**:

| Category                 | Applies when the agent runs…              |
| ------------------------ | ----------------------------------------- |
| **Every-Place Surface**  | anywhere — flows, chat, and voice         |
| **Flow**                 | as a node in a flow                       |
| **Chat**                 | in a chat                                 |
| **Realtime (Voice)**     | as a voice agent                          |

Put the surface in the category that matches where the agent will use the tool,
or in **Every-Place Surface** if it should always be available.

> Don't add MCP tools under **Realtime (Voice)**. The category shows the hint
> *"In realtime, MCP tools are ignored and only the first knowledge collection
> is used."* — a voice agent silently behaves as if the tool weren't attached.

Each category has its own two buttons:

- **Add From Shared** — attach an existing shared surface to this category.
- **Create Surface** — create a new agent-specific surface in this category.

### Adding the MCP tool

You can only pick MCP tools while creating or editing an **agent-specific**
surface. A surface attached with **Add From Shared** is read-only inside the
agent view — it carries a **Shared** badge, and its only actions are **Open in
Shared Surfaces** (to edit it where it lives) and **Detach from this place**.

1. In the category you want, click **Create Surface**.
2. Give the surface a name (for example `GitHub Access`).
3. Select the **Tools** tab, then the **MCP Tools** sub-tab.
4. Click **Select tools**. Use the *"Search MCP tools..."* box to filter, then
   check the MCP tool you registered in Step 1.
5. The selected tools appear in a table below, each with an **X** to remove it.

Your changes are saved as you make them — there is no separate save button.

If the tool isn't in the list because you haven't registered it yet, use the
**Add MCP tool** button on this sub-tab — it opens the same dialog as Step 1,
and the new tool is selected automatically once created.

> Anything you create through **Add MCP tool** is added to the **org-wide
> catalog**, not just to this agent. It will appear in the Tools → MCP list and
> be selectable by every other agent in the organization.

To add the tool to a **shared** surface instead, open the **Shared Surfaces**
section in the left explorer, select the surface, and use the same
**Tools** → **MCP Tools** → **Select tools** path there.

---

## Step 3: Use the tool in a flow

Surfaces are attached to nodes on the flow canvas. Both **Agent** nodes and
**Task** nodes support them.

1. Open your flow in the editor.
2. Click the Agent node (or Task node) that should use the tool. Its side panel
   opens.
3. Find the field labeled **Surface (Group of Permissions)**. When nothing is
   attached it reads **Assign surface**.
4. Open the dropdown. Surfaces are grouped:
   - **Agent Surfaces** — surfaces owned by the selected agent definition.
   - **Shared Surfaces** — surfaces available to any agent.
   - **Local surface** — a surface that exists only on this node (see below).
5. Check the surface that contains your MCP tool. You can attach several
   surfaces at once; the field then summarises them, for example
   *"2 assigned + 1 local"*.

When you pick an agent definition on a brand-new node, the surfaces that agent
already owns are attached automatically — check the field to confirm the one you
need is among them.

Use **View Summary** next to the field to see the combined set of permissions
that will actually apply to the node.

### Attaching a tool to just one node

If a tool should be available on one node only, and you don't want a reusable
surface for it, create a **local surface**:

1. Open the **Surface (Group of Permissions)** dropdown.
2. Click the **+** on the **Local surface** group header. The **Create Local
   Surface** dialog opens.
3. Pick MCP tools exactly as in Step 2 — **Tools** tab → **MCP Tools**
   sub-tab → **Select tools**.
4. Confirm with the checkmark button.

The node now shows **Local surface** as attached. To change it later, click the
edit icon on the **Local surface** row.

Two things to know about local surfaces:

- **A node can have at most one.** Once it exists, the **+** disappears.
- **Unchecking "Local surface" deletes it**, along with all of its tool
  selections, with no confirmation. Use the edit icon to modify it instead of
  removing and re-adding.

---

## If something doesn't work

Because nothing is verified when you save, most problems show up the first time
an agent runs.

| What you see                                        | Likely cause                                                                                        |
| --------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Task fails with *"MCP server unreachable"*          | Wrong **Transport** URL, the server is down, or it is not reachable from EpicStaff. An authentication failure can also appear this way — check the **Auth** secret too. |
| Task fails with *"Tool ... not found on MCP server"* | The **Tool Name** doesn't match any tool on that server. Check spelling and case against the server's documentation. |
| The agent ignores the tool, no error                | The tool isn't reachable through any attached surface. Re-check Step 2 and Step 3, and use **View Summary** on the node. |
| The tool errors only sometimes                      | The server is rejecting the arguments the model sent, or the call is timing out. Raise **Timeout**, and make sure the tool's description on the server explains its arguments clearly. |
| Connection is slow to start                         | Raise **Init Timeout**. Every call re-establishes the connection to the server, so a slow server affects every invocation. |

A failure while *loading* the tool (bad URL, wrong tool name) stops the whole
task before it starts. A failure *during* a call (bad arguments, timeout) is
reported back to the agent, which can adjust and retry on its own.

---

## Current limitations

- **HTTP/SSE servers only.** MCP servers that run as a local subprocess
  (`stdio` transport) are not supported — there is no way to specify a command
  to run.
- **Token authentication only.** A single stored secret is sent as the server's
  auth credential. Custom headers and environment variables are not supported.
- **No tool discovery.** EpicStaff never lists the tools a server offers; you
  always enter the tool name by hand.
- **Realtime and voice agents cannot use MCP tools.** They are skipped without
  an error message, so a voice agent will simply behave as if the tool were not
  attached.
- **Tools are always granted, never blocked.** You cannot deny a specific MCP
  tool for one agent while a surface grants it. To revoke access, detach the
  surface that grants it.

---

## Related

- `docs/secrets/` — creating and managing secrets
- `docs/tools/tools-configuration.md` — configuring Python code tools
- `docs/agents/surfaces.md` — how surfaces are modelled and combined
