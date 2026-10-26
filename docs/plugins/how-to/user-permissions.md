# Give people permissions in your plugin

Your manifest declares what people can do **inside your plugin** (`user_permissions`). EpicStaff
decides, per organization and per role, who gets which of those actions, the same way it decides
who may edit flows or manage roles. You never manage people or roles yourself.

## Declare the actions

```json
"user_permissions": [
  { "action": "read",   "description": "Open Weather and see forecasts.",
    "defaults": { "org_admin": true, "member": true, "viewer": true } },
  { "action": "update", "description": "Add and remove saved places.",
    "defaults": { "org_admin": true, "member": true, "viewer": false } },
  { "action": "delete", "description": "Change the organization's Weather settings.",
    "defaults": { "org_admin": true, "member": false, "viewer": false } }
]
```

- `action` is one of EpicStaff's action codes: `read`, `create`, `update`, `delete`, `export`,
  `use`. EpicStaff shows them as View, Create, Edit, Delete, Export and Use; the `description` is
  what the action means in your plugin, shown as the tooltip in the Roles matrix.
- `read` is required: it is what lets a person open the plugin at all. A role that gets any action
  must get `read` too: the manifest's `defaults` must say so (upload refuses them otherwise), and
  the Roles matrix refuses other actions without View (`400 invalid_plugin_role_permissions`).
- The `defaults` must nest: whatever Viewer gets, Member gets too, and whatever Member gets, Org
  Admin gets too.
- Declare only actions your plugin really checks.

## Who gets what

A person's actions on your plugin come from their role in the organization they are working in:

| Role | Actions |
|---|---|
| Built-in **Org Admin**, **Member**, **Viewer** | The manifest's `defaults` for that role. No organization can change them; the Roles matrix shows them read-only |
| Built-in **Superadmin** (the role of the first SuperAdmin's membership, usually in the default organization) | The manifest's `org_admin` defaults while the person is a SuperAdmin, read-only like the other built-in roles. Someone whose SuperAdmin rights were revoked gets nothing through it |
| A **custom role** | What the organization's admins tick for it in the Roles matrix. Nothing until they do |
| SuperAdmin who is not a member of the organization | Nothing: being a SuperAdmin gives no action on a plugin; SuperAdmins administer plugins, they do not use them in organizations they do not belong to |

Actions are kept per organization: ticking View for a custom role of one organization gives
nothing in another, and a plugin row appears in an organization's Roles matrix only while the
plugin is running and granted to that organization. A person with `read` sees the plugin in the
Apps list.

## The Roles matrix

Organization admins find a **Plugins** group in the Roles matrix with one row per plugin granted
to the organization, and a cell for each action the plugin declares. They can change a custom
role's actions only within their own reach: an admin can tick or untick only actions they hold
on that plugin themselves (a SuperAdmin can change any). Cells outside that reach are disabled;
an action outside it that the role already has (a SuperAdmin gave it) stays as it is when the
admin saves the rest of the role. A request that adds or removes such an action anyway is
refused with `403 permission_escalation_denied`. Built-in roles cannot be edited
(`403 built_in_role_immutable`).

The same reach applies to giving people roles: an admin cannot make someone a member with a
role, or move them to a role, that has plugin actions the admin does not hold on that plugin in
the organization (`403 permission_escalation_denied`). Built-in roles count with their manifest
defaults. This holds while the plugin platform is turned off too: a role's plugin actions are
kept and apply again when it is turned back on.

Deleting a custom role, or the plugin's grant to the organization, deletes the role's actions on
the plugin. Copying a role to another organization does not copy its plugin actions yet.

## Use them in your plugin

EpicStaff uses `read` to decide who sees your plugin in the Apps list, and the action an
[app menu](../reference/manifest.md#app-menu) entry names (`permission`) to decide who sees that
entry. Hiding an entry protects nothing: its page is still reachable by its path for everyone who
may open the plugin. Every request your backend receives in `user` mode carries the person's
actions in the [gateway context](../reference/gateway-context.md) as `permissions` (for example
`["read", "update"]`): check them on the server for anything that changes data, never only in
the page. When your backend acts for a person outside a request of theirs, the
[service account API](../reference/service-account-api.md)'s people endpoint gives the same
actions, and the person's own EpicStaff rights.
