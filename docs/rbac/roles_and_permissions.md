# Roles and Permissions

The permissions surface FE consumes to render role tables, gate UI
actions, and resolve the caller's effective access inside an active
organization. This doc covers the permission catalog, the per-user
effective-permissions endpoint, the role read endpoints, and the
`X-Organization-Id` header contract. Built-in roles are immutable.
Custom roles are out of scope for this iteration.

Base URL in examples: `http://localhost:8000`.

---

## Quick reference

| Method | Path | Auth | Org transport |
|---|---|---|---|
| GET | `/api/permissions/catalog/` | required (JWT or API key) | none |
| GET | `/api/permissions/me/` | required (JWT or API key) | `X-Organization-Id` header |
| GET | `/api/admin/roles/` | `HasOrgPermission(ROLES, READ)` | `X-Organization-Id` header |
| GET | `/api/admin/roles/{id}/` | `HasOrgPermission(ROLES, READ)` | `X-Organization-Id` header |
| GET | `/api/admin/organizations/{org_id}/roles/` | `HasOrgPermission(ROLES, READ)` | URL kwarg |

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

Required on every active-context endpoint
(`/api/permissions/me/`, `/api/admin/roles/`, `/api/admin/roles/{id}/`,
and future resource endpoints). Missing or non-integer value →
`400 org_context_required`. Header points to an org the caller is not
a member of (and is not superadmin) → `403 org_membership_required`.
Superadmin sets any `org_id` and bypasses the membership check.

`/api/profile/` is the **soft-fail exception** — when the header is
absent, malformed, or points to an inaccessible org, both
`active_organization_id` and `active_permissions` come back `null` and
the rest of the response is unchanged. The boot endpoint must remain
reachable for zero-membership users and users whose only orgs are
deactivated.

`/api/permissions/catalog/` ignores the header — the taxonomy is
static and global.

---

## `GET /api/permissions/catalog/`

Static taxonomy used to render the permission matrix UI. Independent
of caller and org. Cache-friendly.

**Auth:** required. **Header:** none.

**Response 200:**

```json
{
  "actions": ["CREATE", "READ", "UPDATE", "DELETE", "EXECUTE"],
  "resource_types": [
    { "group": "admin",     "key": "USERS",         "label": "Users",         "applicable_actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
    { "group": "admin",     "key": "ROLES",         "label": "Roles",         "applicable_actions": ["READ"] },
    { "group": "admin",     "key": "ORGANIZATIONS", "label": "Organizations", "applicable_actions": ["READ", "UPDATE"] },
    { "group": "workspace", "key": "PROJECTS",      "label": "Projects",      "applicable_actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
    { "group": "workspace", "key": "GRAPHS",        "label": "Graphs",        "applicable_actions": ["CREATE", "READ", "UPDATE", "DELETE", "EXECUTE"] },
    { "group": "workspace", "key": "SESSIONS",      "label": "Sessions",      "applicable_actions": ["READ", "EXECUTE"] },
    { "group": "config",    "key": "LLM_CONFIGS",   "label": "LLM configs",   "applicable_actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
    { "group": "config",    "key": "API_KEYS",      "label": "API keys",      "applicable_actions": ["CREATE", "READ", "DELETE"] }
  ]
}
```

`actions[]` is the full verb set. Each
`resource_types[].applicable_actions` is the subset of actions that
make sense for that resource — the matrix is resource rows × action
columns, and cells outside `applicable_actions` render as `—` (cannot
be checked). `group` (`admin` / `workspace` / `config`) sections the
matrix in the UI.

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
    "USERS": ["READ"],
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

## `GET /api/admin/roles/`

List roles visible in the active organization. Returns built-in roles
plus any org-scoped custom roles (when those land later).

**Auth:** `HasOrgPermission(ROLES, READ)`.
**Header:** `X-Organization-Id` required.

**Response 200:**

```json
[
  {
    "id": 1,
    "name": "Superadmin",
    "description": "Global administrator. Bypasses every permission check.",
    "is_built_in": true,
    "scope": "global",
    "org_id": null,
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
    "assigned_count": 4,
    "permissions": [
      { "resource_type": "USERS",         "actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
      { "resource_type": "ROLES",         "actions": ["READ"] },
      { "resource_type": "ORGANIZATIONS", "actions": ["READ", "UPDATE"] },
      { "resource_type": "PROJECTS",      "actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
      { "resource_type": "GRAPHS",        "actions": ["CREATE", "READ", "UPDATE", "DELETE", "EXECUTE"] },
      { "resource_type": "SESSIONS",      "actions": ["READ", "EXECUTE"] },
      { "resource_type": "LLM_CONFIGS",   "actions": ["CREATE", "READ", "UPDATE", "DELETE"] },
      { "resource_type": "API_KEYS",      "actions": ["CREATE", "READ", "DELETE"] }
    ]
  },
  {
    "id": 3,
    "name": "Member",
    "description": "Default workspace member.",
    "is_built_in": true,
    "scope": "org",
    "org_id": null,
    "assigned_count": 27,
    "permissions": [
      { "resource_type": "PROJECTS", "actions": ["CREATE", "READ", "UPDATE"] },
      { "resource_type": "GRAPHS",   "actions": ["CREATE", "READ", "UPDATE", "EXECUTE"] },
      { "resource_type": "SESSIONS", "actions": ["READ", "EXECUTE"] }
    ]
  }
]
```

Field notes:

- `is_built_in: true` — protected from edit / delete (see "Built-in
  immutability" below).
- `scope` — `"global"` for system-wide roles (Superadmin), `"org"`
  for org-scoped roles.
- `org_id` — `null` for built-in roles; set to the owning org id for
  future custom roles.
- `assigned_count` — `OrganizationUser` rows referencing this role in
  the active org. For the **Superadmin role this is typically 0**:
  superadmin authority comes from `User.is_superadmin`, not from a
  membership row. The FE should source the "global superadmins" count
  from the user-list, not from this field.
- `permissions[]` for the Superadmin row is **empty** — authority is
  the flag, not the bitmask. The FE should render Superadmin as "all
  cells checked" without consulting `permissions`.

**Errors:** `400 org_context_required`, `403 permission_denied`,
`403 org_membership_required`, `404 organization_not_found`.

---

## `GET /api/admin/roles/{id}/`

Single role detail. Same shape as one element of the list response.

**Auth:** `HasOrgPermission(ROLES, READ)`.
**Header:** `X-Organization-Id` required.

**Errors:** `400 org_context_required`, `403 permission_denied`,
`403 org_membership_required`, `404 role_not_found`.

---

## `GET /api/admin/organizations/{org_id}/roles/`

Target-context variant — used by superadmin and by cross-org admins to
audit another org's roles without switching active context. The org is
in the URL; the header is ignored.

**Auth:** `HasOrgPermission(ROLES, READ)` against `{org_id}` in the
URL. Anyone with that org's ROLES read permission can call it.

**Response 200:** same shape as `GET /api/admin/roles/` — a list of
role objects.

**Errors:** `403 permission_denied`, `404 organization_not_found`.

---

## Built-in immutability

Built-in roles (`is_built_in: true`) cannot be edited or deleted.
Write endpoints will be added in a later iteration for custom roles;
the guard is already in place so any future write attempt against a
built-in role responds with:

```json
{
  "status_code": 403,
  "code": "built_in_role_immutable",
  "message": "Built-in roles cannot be modified or deleted."
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

Caller is a member but the role does not include the required
(resource_type, action) tuple.

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
