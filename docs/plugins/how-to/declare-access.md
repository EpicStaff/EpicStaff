# Declare what your backend may do

Your backend calls EpicStaff's API as the plugin's service account in each organization the
plugin is granted to ([Service account API](../reference/service-account-api.md)). The manifest's
`access` is everything that service account may do there. Declare the least you need: the
SuperAdmin approving your plugin and the Org Admins of every organization it is granted to read
the list, with your reasons.

## Declare it

```json
"access": [
  { "resource_type": "flows", "actions": ["read", "create", "update", "use"],
    "reason": "Creates the Weather forecast flow and runs it for you." },
  { "resource_type": "files", "actions": ["read", "create"],
    "reason": "Stores the Weather readme in your organization's storage." },
  { "resource_type": "secrets", "actions": ["read", "create", "use"],
    "reason": "Stores the LLM key an admin enters on the Weather settings page." },
  { "resource_type": "llm_configs", "actions": ["read", "create"],
    "reason": "Creates the LLM config for Weather summaries." }
]
```

- `resource_type` and `actions` are the terms of EpicStaff's Roles page:
  `GET /api/permissions/catalog/` lists every resource type and its actions. One entry per type.
- `reason` says why, in words an administrator can judge.
- `access` needs a `backend`: only a backend can call EpicStaff.
- Six types cannot be declared, because their endpoints never accept a plugin's credentials:
  `organizations`, `memberships`, `roles`, `api_keys`, `audit` and `chats`. Upload refuses them.

## Pick the actions

Each call needs the action its endpoint needs from a person:

| To | Declare |
|---|---|
| List or read flows, sessions and a run's result (`GET /api/sessions/{id}/`) | `flows: read` |
| Create a flow, or import one | `flows: create` |
| Change a flow (save it, add nodes) | `flows: update` |
| Run a flow, stop a run, or write schedule, webhook or Telegram trigger nodes | `flows: use` too |
| Store a file in the organization's storage | `files: create` (`files: update` to replace one) |
| Store a secret, and refer to it from a configuration (only secrets the plugin created) | `secrets: create`, `secrets: use` |
| Create an LLM configuration; list the LLM models | `llm_configs: create`; `llm_configs: read` |

Writing trigger nodes needs `flows: use` because a trigger starts runs by itself; the review warns
when `flows` has `create` or `update` without `use`. Secrets have no `update`: replace one by
creating a new secret and deleting the old (`secrets: delete`).

## What the declaration does not give

- **Nothing outside the organization.** A service account acts only in the organization its
  grant is to; every other organization's rows are "not found".
- **No one else's secrets.** `secrets: use` refers only to secrets the plugin created; a reference
  to any other secret of the organization is refused (`400 invalid`).
- **Nothing while it is suspended.** A suspended plugin's keys stop working in that organization,
  and runs that use what it owns there are refused ([the plugin lifecycle](../explanation/lifecycle.md)).
- **Nothing that only people do.** Personal filter presets, tool favorites, the flow assistant,
  voice sessions and notification mail refuse service accounts, whatever the declaration.
- **Nothing beyond the declaration on behalf of a person.** Calling on behalf of an Org Admin
  does not add their rights. And calling on behalf of a Viewer does not remove yours: check the
  person's own `epicstaff_permissions` before you do something for them they could not do
  themselves ([on behalf of a person](../reference/service-account-api.md#on-behalf-of-a-person)).

## What administrators see

- The SuperAdmin reviews the declaration, with your reasons, before approving the package.
- Org Admins see, under **Settings → Plugin activity**, each plugin acting in their organization
  with its declaration, and every change it made there.
- Everything the service account creates is recorded as the plugin's.

Changing `access` later needs a new version of the plugin and a new approval.
