# Roles and Permissions

The permissions surface FE consumes to render role tables, gate UI
actions, and resolve the caller's effective access inside an active
organization. This doc covers the permission catalog, the per-user
effective-permissions endpoints (single-org and cross-org), the flat
role management surface (list / detail / create / update / delete),
and the `X-Organization-Id` header contract. Built-in roles are
immutable; custom roles are organization-scoped and fully manageable
by anyone holding the relevant ROLES permission in that org.

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Auth |
|---|---|---|
| GET | `/api/permissions/catalog/` | required |
| GET | `/api/permissions/me/` | required + `X-Organization-Id` |
| GET | `/api/permissions/me/orgs/` | required |
| GET | `/api/admin/roles/` | `HasResourcePermissionAnywhere(ROLES, READ)` |
| GET | `/api/admin/roles/{id}/` | READ in the role's org |
| POST | `/api/admin/roles/` | CREATE in body `org_id` + ceiling |
| PATCH | `/api/admin/roles/{id}/` | UPDATE in role's org + ceiling |
| DELETE | `/api/admin/roles/{id}/` | DELETE in role's org |

---

## The `X-Organization-Id` header

The header carries the **active organization** — the workspace the
caller is currently operating in. It is a runtime selection, not a
session-persisted setting. Two distinct concepts:

- **Active org (header)** — set by the FE interceptor on every
  active-context request. The backend resolves the caller's role +
  permissions in that org and gates the response.
- **Target org (URL path)** — embedded in admin URLs like
  `/api/admin/organizations/{org_id}/...`. The header is ignored on
  these endpoints; the path wins. Used by superadmin and cross-org
  admins to operate on one specific org without switching active
  context.

Required on `/api/permissions/me/` and other active-context resource
endpoints outside this doc's scope. Missing or non-integer value →
`400 org_context_required`. Header points to an org the caller is not
a member of (and is not superadmin) → `403 org_membership_required`.
Superadmin sets any `org_id` and bypasses the membership check.

The role management endpoints below do **not** consult this header at
all. `GET /api/admin/roles/` is cross-org by design (see its own
section below); detail/create/update/delete resolve their org from
the role row itself (detail/update/delete) or from `org_id` in the
request body (create) — never from a header.

`/api/profile/` is the **soft-fail exception** — when the header is
absent, malformed, or points to an inaccessible org, both
`active_organization_id` and `active_permissions` come back `null` and
the rest of the response is unchanged. The boot endpoint must remain
reachable for zero-membership users and users whose only orgs are
deactivated.

`/api/permissions/catalog/` ignores the header — the taxonomy is
static and global. So does `/api/permissions/me/orgs/` — it is
inherently multi-org.

---

## `GET /api/permissions/catalog/`

Static taxonomy used to render the permission matrix UI. Independent
of caller and org. Cache-friendly.

**Auth:** required. **Header:** none.

**Response 200:**

```json
{
  "actions": [
    { "code": "create", "label": "Create", "bit": 1 },
    { "code": "read",   "label": "View",   "bit": 2 },
    { "code": "update", "label": "Edit",   "bit": 4 },
    { "code": "delete", "label": "Delete", "bit": 8 },
    { "code": "export", "label": "Export", "bit": 16 }
  ],
  "resource_types": [
    { "code": "organizations",     "label": "Organizations",       "group": "admin",     "description": "Rename and manage organization settings",        "applicable_actions": ["read", "update"], "platform_actions": ["create", "delete"] },
    { "code": "memberships",       "label": "Members",             "group": "admin",     "description": "Add, remove, and re-role members within an org", "applicable_actions": ["create", "read", "update", "delete"] },
    { "code": "roles",             "label": "Roles",               "group": "admin",     "description": "Create/edit custom roles and assign to users",   "applicable_actions": ["create", "read", "update", "delete"] },
    { "code": "flows",             "label": "Flows",               "group": "workspace", "description": "Workflow definitions and their nodes",           "applicable_actions": ["create", "read", "update", "delete", "export"] },
    { "code": "agents",            "label": "Agents",              "group": "workspace", "description": "AI agent configurations",                        "applicable_actions": ["create", "read", "update", "delete", "export"] },
    { "code": "tools",             "label": "Tools",               "group": "workspace", "description": "Tool definitions and configurations",            "applicable_actions": ["create", "read", "update", "delete"] },
    { "code": "knowledge_sources", "label": "Knowledge Sources",   "group": "workspace", "description": "RAG collections and embeddings",                 "applicable_actions": ["create", "read", "update", "delete"] },
    { "code": "files",             "label": "Storage (Files)",     "group": "workspace", "description": "Files and folders in organization storage",      "applicable_actions": ["create", "read", "update", "delete", "export"] },
    { "code": "projects",          "label": "Projects",            "group": "workspace", "description": "Organize AI agents and tasks",                   "applicable_actions": ["create", "read", "update", "delete", "export"] },
    { "code": "llm_configs",       "label": "LLM Configs",         "group": "config",    "description": "LLM model configurations and settings",          "applicable_actions": ["create", "read", "update", "delete"] },
    { "code": "secrets",           "label": "API Keys / Secrets",  "group": "config",    "description": "Provider API keys, credentials, sensitive config", "applicable_actions": ["create", "read", "update", "delete"] }
  ]
}
```

`actions[]` is the full verb set. Each
`resource_types[].applicable_actions` is the subset of actions that
make sense for that resource **and are grantable into a custom role** —
the matrix is resource rows × action columns, and cells outside
`applicable_actions` render as `—` (cannot be checked). `group`
(`admin` / `workspace` / `config`) sections the matrix in the UI.

Every resource also carries **`platform_actions`** — global,
superadmin-only actions that are **never grantable** into a custom role.
It is `[]` for every resource except `organizations`, whose `create`
(create a new org) and `delete` (deactivate/reactivate) are platform-level.
Render `platform_actions` cells as disabled / "superadmin-only". Submitting
a platform action in a role's `permissions[]` is a `400 invalid`
("platform-level … cannot be granted").

Each entry additionally carries **`recommended_with`**, elided from the
listing above for brevity — see the next section.

### `recommended_with`

Permissions worth granting alongside another. **Advisory only** — nothing
here is enforced, and a role that ignores every recommendation saves
normally. It exists so the matrix UI can nudge the author toward a
coherent role instead of one that grants edit rights without the read
access needed to use them.

```json
{
  "code": "flows",
  "applicable_actions": ["create", "read", "update", "delete", "export"],
  "platform_actions": [],
  "recommended_with": {
    "create": [
      { "resource_type": "flows",       "action": "read" },
      { "resource_type": "projects",    "action": "read" },
      { "resource_type": "llm_configs", "action": "read" }
    ],
    "read": [
      { "resource_type": "projects",    "action": "read" },
      { "resource_type": "llm_configs", "action": "read" }
    ],
    "update": [
      { "resource_type": "flows",       "action": "read" },
      { "resource_type": "projects",    "action": "read" },
      { "resource_type": "llm_configs", "action": "read" }
    ],
    "delete": [{ "resource_type": "flows", "action": "read" }],
    "export": [{ "resource_type": "flows", "action": "read" }]
  }
}
```

Keys are action codes; values are the cells to suggest when that action is
checked. **Every action in `applicable_actions` is a key** — an empty list
where nothing is recommended — so you can index without nil-checks. Actions
in `platform_actions` never appear: they cannot be granted, so a suggestion
on them is unreachable.

The shape of the advice:

- **Reading** a resource suggests reading whatever it references — a flow
  points at projects and LLM configs, an agent at knowledge sources, tools
  and LLM configs.
- **Creating or editing** suggests the resource's own `read` plus everything
  that read suggests. You cannot sensibly author what you cannot see.
- **Deleting and exporting** suggest only the resource's own `read`.

Suggestions are direct, not transitive: `projects:create` recommends
`flows:create`, and `flows:create` has recommendations of its own. Look up
each cell as the user accepts it and the chain unfolds one step at a time,
which keeps the initial suggestion short and lets the user stop early.

---

## `GET /api/permissions/me/`

The caller's effective permissions in the active organization. The FE
caches this after login (and after every org switch) to drive UI
gating.

**Auth:** required. **Header:** `X-Organization-Id` required.

**Response 200 — non-superadmin caller:**

```json
{
  "is_superadmin": false,
  "role": { "id": 3, "name": "Member" },
  "permissions": {
    "MEMBERSHIPS": ["READ"],
    "ROLES": ["READ"],
    "ORGANIZATIONS": ["READ"],
    "PROJECTS": ["CREATE", "READ", "UPDATE"],
    "GRAPHS": ["CREATE", "READ", "UPDATE", "EXECUTE"],
    "SESSIONS": ["READ", "EXECUTE"],
    "LLM_CONFIGS": ["READ"],
    "API_KEYS": []
  }
}
```

Every `resource_types[].key` from the catalog is always present in
`permissions`, with `[]` for resources the role has no permission on
— the FE can index by key without nil-checks.

**Response 200 — superadmin caller:**

```json
{ "is_superadmin": true, "role": null, "permissions": "*" }
```

`permissions: "*"` is the wildcard — superadmin can do anything on any
resource in any org. Treat as "every cell checked" for matrix renders
and skip per-action gating.

**Errors:** `400 org_context_required`, `403 org_membership_required`,
`404 organization_not_found`.

---

## `GET /api/permissions/me/orgs/`

The caller's effective permissions across **every** organization they
belong to, in one round trip. Used by multi-org UI (org switcher, an
"all my orgs" view) so the FE doesn't have to call
`/api/permissions/me/` once per org.

**Auth:** required. **Header:** none — the endpoint is inherently
multi-org, so there is no single active org to select.

**Response 200 — superadmin caller:**

```json
{ "is_superadmin": true, "permissions": "*" }
```

Superadmin short-circuits to the wildcard without enumerating orgs —
`orgs` is omitted entirely.

**Response 200 — non-superadmin caller:**

```json
{
  "is_superadmin": false,
  "orgs": [
    {
      "org": { "id": 1, "name": "Acme" },
      "role": { "id": 2, "name": "Org Admin" },
      "permissions": {
        "roles": ["create", "read", "update", "delete"],
        "flows": ["create", "read", "update", "delete", "export"]
      }
    },
    {
      "org": { "id": 2, "name": "Beta" },
      "role": { "id": 3, "name": "Member" },
      "permissions": { "roles": [], "flows": ["create", "read", "update"] }
    }
  ]
}
```

One entry per organization the caller has a membership row in. Each
entry's `permissions` uses the same per-resource action-list shape as
`/api/permissions/me/`, just nested under its own org.

**Errors:** none beyond the standard 401 for unauthenticated callers.

---

## `GET /api/admin/roles/`

List roles visible to the caller — every built-in role, plus every
custom role in an organization the caller can READ. Cross-org by
design: there is one caller-wide list, not one list per org, and no
active-org selection is involved.

**Auth:** `HasResourcePermissionAnywhere(ROLES, READ)` — passes if the
caller is superadmin, or holds READ on ROLES in **at least one** org.
This is a coarse door gate; which orgs' custom roles actually come
back is then resolved per-org inside the query (see `?org_ids=`
below). **Header:** none.

**Query params:**

- `?org_ids=1,2` — restrict the custom-role results to these org ids
  (comma-separated integers). Requesting an org id the caller cannot
  READ roles in (and is not superadmin) fails loud — `403
  permission_denied` for the whole request. It never silently drops
  the forbidden id and returns the rest.
- Omitted — every custom role in every org the caller can READ.
  Superadmin gets every custom role in every org, unfiltered.
- `?page=`, `?page_size=` — standard pagination over `results` only
  (default page size 50, max 200).

**Response 200:**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 5,
      "name": "Billing Manager",
      "description": "Manage billing and secrets",
      "is_built_in": false,
      "scope": "org",
      "org_id": 1,
      "org": { "id": 1, "name": "Acme Inc" },
      "assigned_count": 2,
      "permissions": [
        { "resource_type": "secrets", "actions": ["read", "update"] }
      ]
    }
  ],
  "built_in_roles": [
    {
      "id": 1,
      "name": "Superadmin",
      "description": "Global administrator. Bypasses every permission check.",
      "is_built_in": true,
      "scope": "global",
      "org_id": null,
      "org": null,
      "assigned_count": 0,
      "permissions": []
    },
    {
      "id": 2,
      "name": "Org Admin",
      "description": "Full administrative authority within the organization.",
      "is_built_in": true,
      "scope": "org",
      "org_id": null,
      "org": null,
      "assigned_count": 0,
      "permissions": [
        { "resource_type": "flows", "actions": ["create", "read", "update", "delete", "export"] }
      ]
    }
  ]
}
```

Field notes:

- `results` — **custom roles only** (`is_built_in: false`), paginated.
  `count` / `next` / `previous` describe this list alone.
- `built_in_roles` — always the full, unpaginated set of the four
  built-in roles (Superadmin, Org Admin, Member, Viewer). Not affected
  by `?org_ids=` or pagination — every caller who passes the door gate
  sees all four.
- `is_built_in: true` — protected from edit / delete (see "Built-in
  immutability" below).
- `scope` — `"global"` for Superadmin, `"org"` for every other role.
- `org` / `org_id` — `null` for built-in roles; the owning org for
  custom roles.
- `assigned_count` — `OrganizationUser` rows referencing this role.
  For the Superadmin role this is typically 0 — superadmin authority
  comes from `User.is_superadmin`, not a membership row.
- `permissions[]` for the Superadmin row is **empty** — authority is
  the flag, not the bitmask. Render Superadmin as "all cells checked"
  without consulting `permissions`.

**Errors:** `403 permission_denied` (forbidden `org_ids` entry, or the
door gate itself).

---

## `GET /api/admin/roles/{id}/`

Single role detail. Same shape as one element of `results` /
`built_in_roles` above.

**Auth:** built-in roles are visible to anyone who clears the door gate
(READ on ROLES in at least one org, or superadmin). A custom role
additionally requires READ on ROLES in **that role's own org** —
derived from the row, not from a header or URL kwarg. **Header:**
none.

A role that exists but sits in an org the caller cannot READ responds
`404 role_not_found` — identical to a genuinely missing id, so the
caller cannot probe for the existence of roles in orgs they can't see.

**Errors:** `404 role_not_found`.

---

## `POST /api/admin/roles/`

Create a custom role in an organization.

**Auth:** the door gate, plus CREATE on ROLES in the target org
(service-layer check) and the ceiling rule (below). **Header:** none —
the target org is `org_id` in the body.

**Body:**

```json
{
  "org_id": 1,
  "name": "Billing Manager",
  "description": "Manage billing and secrets",
  "permissions": [
    { "resource_type": "secrets", "actions": ["read", "update"] }
  ]
}
```

`name` is required: non-blank, 255 characters or fewer, and cannot
match one of the four built-in names case-insensitively (`Superadmin`
/ `Org Admin` / `Member` / `Viewer`) or an existing role name in the
same org case-insensitively → `400 role_name_conflict`. `description`
is optional, 1000 characters or fewer. `permissions` is a list of
`{resource_type, actions}`; an action outside that resource's
`applicable_actions` (from the catalog) fails validation; an entry
that reduces to a zero bitmask is dropped rather than stored.

**Response 201:** the created role, same shape as a list element.

**Errors:** `400` (field validation), `400 role_name_conflict`,
`403 permission_denied`, `403 permission_escalation_denied`.

---

## `PATCH /api/admin/roles/{id}/`

Edit a custom role's `name`, `description`, and/or `permissions` — any
subset; omitted fields are left untouched. Sending `permissions` is a
**full replacement** of the role's permission set, not a merge.

**Auth:** UPDATE on ROLES in the role's own org, plus the ceiling rule
when `permissions` is included. Built-in roles always reject with
`403 built_in_role_immutable` before any other check runs.
**Header:** none.

**Errors:** `403 built_in_role_immutable`, `400` (field validation),
`400 role_name_conflict`, `403 permission_denied`,
`403 permission_escalation_denied`.

---

## `DELETE /api/admin/roles/{id}/`

Delete a custom role. Every member currently on the role is
reassigned to the built-in **Viewer** role first — deleting a role
never evicts a member from the organization.

**Auth:** DELETE on ROLES in the role's own org. Built-in roles always
reject with `403 built_in_role_immutable`. **Header:** none.

**`?dry_run=true`** — preview only, no mutation:

```json
{
  "role_id": 5,
  "assigned_count": 2,
  "affected_users": [
    { "user_id": 9, "email": "a@acme.test", "display_name": "A" },
    { "user_id": 10, "email": "b@acme.test", "display_name": "B" }
  ]
}
```

**Without `dry_run`** — deletes the role and performs the reassignment:

```json
{ "reassigned_count": 2 }
```

**Errors:** `403 built_in_role_immutable`, `403 permission_denied`,
`404 role_not_found`.

---


## Built-in immutability

Built-in roles (`is_built_in: true`) can never be edited or deleted —
not even by superadmin. `PATCH` and `DELETE` on
`/api/admin/roles/{id}/` both check this before any other
authorization or validation runs:

```json
{
  "status_code": 403,
  "code": "built_in_role_immutable",
  "message": "Built-in roles cannot be edited or deleted."
}
```

The FE should disable Edit / Delete buttons on rows where
`is_built_in: true` rather than relying on the error envelope.

---

## Common error envelopes

### `400 org_context_required`

```json
{
  "status_code": 400,
  "code": "org_context_required",
  "message": "X-Organization-Id header is required for this endpoint."
}
```

Active-context endpoint called without the header, or with a value
that is not a positive integer.

### `403 org_membership_required`

```json
{
  "status_code": 403,
  "code": "org_membership_required",
  "message": "You are not a member of the requested organization."
}
```

Caller is authenticated but is not a member of the org pointed to by
the header (and is not superadmin). FE should clear the cached header
and redirect to the org picker.

### `403 permission_denied`

```json
{
  "status_code": 403,
  "code": "permission_denied",
  "message": "You do not have permission to perform this action."
}
```

Caller is a member (or, for the roles door gate, any authenticated
non-member) but does not hold the required (resource_type, action)
tuple anywhere it is required.

### `403 permission_escalation_denied`

```json
{
  "status_code": 403,
  "code": "permission_escalation_denied",
  "message": "You cannot grant permissions you do not have in this organization."
}
```

Raised by `POST` / `PATCH` on `/api/admin/roles/` when the submitted
`permissions[]` includes a bit the caller does not hold themselves in
that org — the ceiling rule. Superadmin bypasses it.

### `400 role_name_conflict`

```json
{
  "status_code": 400,
  "code": "role_name_conflict",
  "message": "A role with this name already exists in this organization."
}
```

Raised by `POST` / `PATCH` on `/api/admin/roles/` when `name` collides
case-insensitively with an existing role in the same org — including
the four built-in names. The caller renames; names are never silently
overwritten.

### `404 role_not_found`

```json
{
  "status_code": 404,
  "code": "role_not_found",
  "message": "Role not found."
}
```

Returned for a genuinely missing role id, a non-integer id, and a role
that exists but sits in an org the caller cannot READ — the three
cases are indistinguishable by design.

### `404 organization_not_found`

```json
{
  "status_code": 404,
  "code": "organization_not_found",
  "message": "Organization not found."
}
```

---

## FE matrix rendering

Combine the catalog (column headers + valid cells per row) with a role
response (checked cells):

```js
function renderRoleMatrix(catalog, role) {
  const rolePerms = indexBy(role.permissions, "resource_type");

  return catalog.resource_types.map(rt => {
    const granted = new Set(rolePerms[rt.key]?.actions ?? []);
    const applicable = new Set(rt.applicable_actions);

    return {
      label: rt.label,
      group: rt.group,
      cells: catalog.actions.map(action => {
        if (!applicable.has(action)) return { kind: "na" };          // render —
        return { kind: "cell", checked: granted.has(action) };
      }),
    };
  });
}
```

Special cases handled outside this loop:

- `role.name === "Superadmin"` → render every applicable cell as
  checked, ignore `permissions[]`.
- `permissions === "*"` on `/api/permissions/me/` → same wildcard
  treatment for the action-gating layer.

When the user checks a cell, read its suggestions off the same catalog row:

```js
function suggestionsFor(catalog, resourceCode, action, checkedCells) {
  const rt = catalog.resource_types.find(r => r.code === resourceCode);
  return (rt.recommended_with[action] ?? [])
    .filter(c => !checkedCells.has(`${c.resource_type}:${c.action}`));
}
```

Highlight what comes back, or offer to check it. Accepting a suggestion is
itself a checked cell, so calling `suggestionsFor` again on that cell walks
the next step of the chain.

---

## FE bootstrap flow

1. On login, call `GET /api/profile/` (no header). Read `memberships[]`.
2. Pick an active org (or restore last choice from local state).
3. Set `X-Organization-Id: <id>` on the HTTP interceptor as a default
   header for every subsequent request.
4. Refetch `GET /api/profile/` with the header. The response now
   embeds `active_organization_id` + `active_permissions` — cache them
   in FE state.
5. On org switch: update the header, refetch `/api/profile/`, replace
   cached state.
6. On mid-session `403 org_membership_required` (org deactivated,
   membership removed): clear the header, clear cached permissions,
   redirect to the org picker.

---

## Edge cases

| Scenario | Response | FE handling |
|---|---|---|
| Header missing on active-context endpoint | `400 org_context_required` | Treat as bug — interceptor must always set the header after login. |
| Header value is `"abc"` or empty | `400 org_context_required` | Treat as bug — sanitize before send. |
| Header points to org caller isn't a member of | `403 org_membership_required` | Clear header, redirect to org picker. |
| Header points to deactivated org | `403 org_membership_required` | Same as above. The org is filtered from `memberships[]` on `/api/profile/` so the picker won't re-suggest it. |
| Header missing on `/api/profile/` | `200` with both active fields `null` | Show org picker; do not gate UI yet. |
| Header malformed on `/api/profile/` | `200` with both active fields `null` (soft-fail) | Same as above. |
| Zero-membership user calls `/api/profile/` | `200` with `memberships: []` and both active fields `null` | Show "ask an admin to invite you" empty state. |
| Superadmin sets header to any org (member or not) | `200` — superadmin bypasses membership check | No special handling. |

---

## Resource scoping coverage (EST-2423)

Every workspace/config resource is now scoped to the active org and gated by its `resource_type`.
Two patterns beyond plain org ownership:

- **Hybrid (built-in + custom).** Custom **models** (`llm-models`, `embedding-models`,
  `realtime-models`, `realtime-transcription-models` via `is_custom`) and **python-code tools**
  (`python-code-tool` via `built_in`) show *built-ins to every org* + *that org's custom rows*.
  Creating one through the API always makes it the org's custom row (never a global built-in).
- **Global registry, superadmin-only writes.** `providers`, `ngrok-config`, the `default-*` config
  singletons, and `voice-settings`/Twilio are readable by any member but writable only by a
  superadmin (`voice-settings`/Twilio are superadmin for **read too** — they hold the platform
  Twilio secret). Cross-org file `move`/`copy` is likewise superadmin-only.

| Resource type | Endpoints (examples) | Member | Org Admin |
|---|---|---|---|
| FLOWS | graphs, nodes, sessions, **labels**, **webhook-triggers** | C R U | C R U D E |
| AGENTS | agents, realtime-agents, **realtime-agent-chats** | C R U | C R U D E |
| PROJECTS | crews, tasks | C R U | C R U D E |
| TOOLS | python-code-tool(-configs/-fields), mcp-tools, python-code | C R U | C R U D |
| KNOWLEDGE_SOURCES | source-collections, documents, naive-rag, graph-rag, indexing | **R** | C R U D |
| LLM_CONFIGS | llm/embedding/realtime configs **and custom models** | **R** | C R U D |
| FILES | storage | C R U E | C R U D E |

**Cross-org references are rejected** like a non-existent pk (`400 Invalid pk … does not exist`): a
write in org A cannot attach org B's tool (`tool_ids`), knowledge collection, rag, or LLM/embedding
config.

**Deprecated / deferred (not gated):** `/api/tools/`, `/api/tool-configs/`, `*-tags`,
`template-agents`, `environment/config` (deprecating); `memory`, `realtime-session-items`,
`python-code-result` (opaque runtime — pending a denormalized org); and the run/voice/trigger
execution callbacks.
