# Service account API

A plugin's backend calls EpicStaff's API as the plugin's **service account** in an organization.
This page describes the service account, its keys, what it may do, calling on behalf of a person,
the three endpoints only plugin backends use, and what EpicStaff records about those calls. The
Python SDK wraps all of it ([Call EpicStaff from your backend](../how-to/call-epicstaff-from-the-backend.md)).

## Service accounts and keys

A plugin with a backend gets one service account in each organization it is granted to, created
with the grant. A plugin without a backend gets none.

Each service account has a key. Keys come in the runtime file's `service_accounts`, keyed by
organization id as text ([Runtime](runtime.md)):

```json
"service_accounts": { "3": { "key": "esp-…", "org_name": "Acme", "grant_state": "active" } }
```

- An organization is listed while its grant holds a key: `granting` (the install hook runs) and
  `active`. Read `grant_state` as text; a later EpicStaff may add states.
- EpicStaff stores only a key's hash, so it mints a new key every time the plugin node fetches the
  runtime file: at every start or restart of your process, and whenever the list of
  organizations changes (a grant created, a grant entering or leaving a key-holding state, an
  organization renamed or deactivated). The key before the newest keeps working for 10 minutes;
  every older one stops at once.
- Read the key from the runtime file for each call (`RuntimeConfig.service_account(org_id)`), never
  keep it. On `401 service_account_not_authenticated`, read the file again and retry once.
- A key works only on calls that reach EpicStaff through the plugins network, at the runtime
  file's `epicstaff_api_url`. Sent to EpicStaff's public address, it gets `401`.
- Keys and the runtime file are secrets: never log them, never send them anywhere but EpicStaff.
- **Suspension.** When a SuperAdmin suspends the plugin in an organization, every key of that
  organization's service account stops at once (`401`), the one inside its 10 minutes included,
  and the organization leaves the runtime file at the node's next fetch. Resuming mints new keys at
  the next fetch; the old ones never work again. See [the plugin lifecycle](../explanation/lifecycle.md).

## Calling EpicStaff

```
GET <epicstaff_api_url>graphs/
Authorization: PluginKey esp-…
X-Organization-Id: 3                    (optional: the key's own organization)
X-EpicStaff-On-Behalf-Of: 17            (optional: see below)
```

- **Organization.** A key belongs to one organization. Without `X-Organization-Id` the call is in
  that organization; naming any other one gets `404 organization_not_found`, as if it did not
  exist, and so does any row of another organization.
- **What it may do.** Exactly the plugin's declared [`access`](manifest.md#access) in that
  organization, through EpicStaff's ordinary endpoints: creating a flow needs `flows: create`,
  running one `flows: use`, storing a file `files: create`, and so on. Anything else gets
  `403 permission_denied`. See [Declare what your backend may do](../how-to/declare-access.md).
- **What it may never do.** Endpoints that only people use refuse it with `403 permission_denied`
  ("Plugin service accounts cannot use this endpoint."): personal audit filter presets, tool
  favorites, the flow assistant, realtime voice sessions and outgoing notification mail. Account,
  organization, role, membership and API-key management, the plugin administration, purging the
  recycle bin and the WebSocket and SSE tickets never read a plugin key (`401`).
- **Secrets.** A service account with `secrets` access creates and lists secrets and refers to them
  (`use`), only to secrets it created itself: a configuration, tool, Python code or trigger that
  references any other secret of the organization is refused (`400 invalid`) on create and on
  every update. A secret's value is never returned. There is no `update`: create a new secret and
  delete the old one.
- **Models.** A service account cannot set where a model sends requests (`base_url`,
  `deployment_id`), on its own models or the organization's; for its own endpoint, put it on its
  own configuration with its own secret. Its other fields stay editable with `llm_configs: update`.
- **Rate.** Each organization's service account may make `requests_per_minute` calls a minute,
  every endpoint counted; over it, `429 throttled` with `Retry-After` ([Limits](limits.md)).
- **What it creates is the plugin's.** EpicStaff records every flow, secret, LLM, embedding or
  realtime configuration, custom model, knowledge source, tool, key-value table, voice channel,
  webhook trigger, agent, surface and stored file the service account creates as owned by the
  plugin, on behalf of a person or not. Folders are never owned: they hold the organization's own
  files too.

## On behalf of a person

`X-EpicStaff-On-Behalf-Of: <user id>` says the call is made for that person, usually the person
whose gateway context the backend is answering. EpicStaff then checks one thing: that the person
may use the plugin in the organization (an active member of the active organization whose role
has `read` on the plugin, under an active grant).

- A value that is not a decimal positive whole number below 2^63 gets `400 invalid_on_behalf_of`.
- Anyone else, for whatever reason, gets `403 on_behalf_of_not_allowed`, the same answer every
  time. While the install hook runs the grant is not active yet, so hooks always run on their own.
- EpicStaff records the person on the session (`principal.email`), in the plugin's activity and
  on what the call creates.
- **The plugin's declared access still caps the call, and the person's own EpicStaff rights are
  not checked.** A person who may only view flows in EpicStaff can still have your plugin create
  one for them. EpicStaff trusts your backend to name the person truthfully and to decide what it
  does for them: read the person's rights from the people endpoint (`epicstaff_permissions`) and
  refuse what they could not do themselves.

## Endpoints for plugin backends

Only a service-account key opens these; a person's login gets `401`. They are counted in the
request rate and never recorded as activity.

### `GET /api/plugin-runtime/me/`

The service account the key belongs to.

```json
{
  "plugin": { "identifier": "weather", "version": "0.4.0" },
  "organization": { "id": 3, "name": "Acme" },
  "grant_state": "active",
  "access": { "flows": ["create", "read", "update", "use"], "files": ["create", "read"] },
  "requests_per_minute": 120,
  "on_behalf_of": null
}
```

`access` lists the declared access in EpicStaff's catalog order. `on_behalf_of` is the checked
person (`{id, email, name}`) when the call sent `X-EpicStaff-On-Behalf-Of`.

### `GET /api/plugin-runtime/people/{user_id}/`

A person who may use the plugin in the service account's organization:

```json
{
  "user": { "id": 17, "email": "ada@example.com", "name": "Ada" },
  "organization": { "id": 3, "name": "Acme" },
  "plugin_permissions": ["read", "delete"],
  "epicstaff_permissions": { "flows": ["create", "read", "update", "use"], "secrets": [], "...": [] }
}
```

- `plugin_permissions`: the person's actions on the plugin, in manifest order, always with
  `read`; the same as their gateway context's `permissions`.
- `epicstaff_permissions`: the person's own rights in EpicStaff from their membership role, in
  the shape of `GET /api/permissions/me/`'s `permissions`: every resource type of the catalog is a
  key. Never `"*"`: a SuperAdmin's membership role counts, and the built-in Superadmin role of a
  current SuperAdmin reads as Org Admin.
- Anyone who may not use the plugin there is `404 person_not_found`: members without `read`,
  inactive users, other organizations' people and unknown ids alike.

### `POST /api/plugin-runtime/people/lookup/`

```json
{ "user_ids": [17, 23, 99] }
```

1 to 100 distinct positive user ids (`400 invalid` otherwise). The answer is
`{"people": [<person>, ...]}`: the people among them who may use the plugin, sorted by user id;
the others are left out.

**Caching.** Rights change: cache a person for at most 30 seconds.

## Activity

Every call a service account makes that changes something (any method but `GET`, `HEAD` and
`OPTIONS`) and succeeds (status below 400) is recorded as plugin activity, apart from the
endpoints above. The Org Admins of the organization see it in **Settings → Plugin activity**
(it needs the Audit View permission), next to the plugins acting in their organization and the
access each declared; a SuperAdmin sees every organization's on the plugin's **Activity** tab.

| Action | Recorded when | Actor | Organization |
|---|---|---|---|
| `api_request` | A service account's call that changed something; with its method, path (never the query string), route, status, the resource it created or named, and `created_count` | The plugin, and the person it acted for | The service account's |
| `package_approved` | A SuperAdmin approved a package (`version`, `trust`) | SuperAdmin | none |
| `grant_created` | A SuperAdmin granted the plugin to an organization | SuperAdmin | the grant's |
| `install_hook_succeeded`, `install_hook_failed` | The install hook reported (`job_id`, `attempt`, and `error` when it failed) | Platform | the grant's |
| `install_hook_retried` | A SuperAdmin retried a failed install hook (`job_id`) | SuperAdmin | the grant's |
| `grant_suspended` | A SuperAdmin suspended the plugin in the organization (`previous_state`, `purge_after`) | SuperAdmin | the grant's |
| `grant_resumed` | A SuperAdmin resumed it (`state`: `active`, or `install_failed` when its install hook never succeeded) | SuperAdmin | the grant's |
| `settings_changed` | A SuperAdmin changed settings (the keys only, never values) | SuperAdmin | none |
| `limits_changed` | A SuperAdmin changed limit overrides (the overrides in force afterwards, one key per limit, such as `memory_mb` and `cpu_priority`) | SuperAdmin | none |
| `restarted` | A SuperAdmin restarted the backend (`restart_generation`) | SuperAdmin | none |
| `database_ready` | The plugin's database is ready: the first time, again after a failure, and after new migrations ran (`migrations_applied`, the number of migrations applied so far) | Platform | none |
| `database_failed` | Setting up the plugin's database failed (`error`); recorded when it starts failing, not again while it keeps failing | Platform | none |
| `database_limit_restored` | The plugin node put back a database limit the plugin's role had changed (`setting`: `statement_timeout`); at most once an hour | Platform | none |

Events name the plugin by its identifier, so they outlive the plugin. Logins to the plugin are
not activity, and neither are runs refused while the plugin is suspended. An event's `detail` holds
only numbers, text, booleans and lists of text. `request.route` is the URL path pattern of the
endpoint, the same form for every endpoint: `api/graphs/<pk>/`, `api/sessions/<session_id>/stop/`.

## Errors

| Code | Status | When |
|---|---|---|
| `service_account_not_authenticated` | 401 | The key is unknown, revoked or replaced more than 10 minutes ago, its grant holds no key, its organization is inactive, or the call did not come through the plugins network |
| `invalid_on_behalf_of` | 400 | A malformed `X-EpicStaff-On-Behalf-Of` |
| `on_behalf_of_not_allowed` | 403 | The person may not use the plugin in the organization |
| `organization_not_found` | 404 | `X-Organization-Id` names another organization |
| `permission_denied` | 403 | The declared access does not cover the call, or only people use the endpoint |
| `person_not_found` | 404 | The people endpoint, for anyone who may not use the plugin |
| `invalid` | 400 | A malformed people lookup |
| `throttled` | 429 | Over `requests_per_minute` |

Every code is in [Error codes](error-codes.md).
