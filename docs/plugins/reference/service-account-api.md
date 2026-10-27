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

- An organization is listed while its grant holds a key: `granting` (the install hook runs),
  `active`, and `upgrading` (the plugin is being upgraded, or its upgrade hook has not finished
  there). Do an organization's background work only while its `grant_state` is `active`. Read
  `grant_state` as text; a later EpicStaff may add states.
- EpicStaff stores only a key's hash, so it mints a new key every time the plugin node fetches the
  runtime file: at every start or restart of your process, and whenever the list of
  organizations changes (a grant created, a grant entering or leaving a key-holding state, an
  organization renamed or deactivated). The key before the newest keeps working for 10 minutes;
  every older one stops at once.
- Read the key from the runtime file for each call (`RuntimeConfig.service_account(org_id)`), never
  keep it. On `401 service_account_not_authenticated`, read the file again and retry once.
- A key works only on calls that reach EpicStaff through the plugins network, at the runtime
  file's `epicstaff_api_url`. Sent to EpicStaff's public address, it gets `401`. A development
  key works only through the development API listener instead: see
  [Development keys](#development-keys).
- Keys and the runtime file are secrets: never log them, never send them anywhere but EpicStaff.
- **Suspension.** When a SuperAdmin suspends the plugin in an organization, every key of that
  organization's service account stops at once (`401`), the one inside its 10 minutes included,
  and the organization leaves the runtime file at the node's next fetch. Resuming mints new keys at
  the next fetch; the old ones never work again. See [the plugin lifecycle](../explanation/lifecycle.md).
- **Uninstall, deleting data, deleting an organization.** Uninstalling the plugin suspends it
  everywhere, with the same effect on keys. An organization whose plugin data is being deleted,
  and an organization that was deleted, have no service account key at all: the organization
  removed hook runs without one ([Delete your data when an organization leaves](../how-to/org-removed-hook.md)).

## Development keys

In plugin development mode a SuperAdmin can download a development runtime file for a plugin
with a backend (Plugins → the plugin → Development). It is the plugin node's runtime file, with
two differences: `service_accounts` holds development keys, and `epicstaff_api_url` is the
development API listener on the machine's loopback, `http://127.0.0.1:<PLUGINS_DEV_API_PORT>/api/`.
`epicstaff-plugin dev` runs your backend with it ([local development](../how-to/local-development.md)).

- A development key looks like any other key and acts for the plugin in one organization, with
  the same declared access, on-behalf-of rules and activity.
- It works only through the development API listener, and only while `PLUGINS_DEV_MODE` is
  true. Through the plugins network it gets `401`, and so does every call once the mode is
  turned off. Node keys, and the plugin node's own key, get `401` on the development listener.
- The file holds one key for each organization whose grant holds a key when it is downloaded.
  The node's keys are not changed, and the plugin node never gets a development key.
- Development keys never expire and are never replaced by the node. They stop working when a
  SuperAdmin downloads the file again (every earlier development key of the plugin stops at once,
  with no overlap), stops development, or suspends the plugin in the organization; resuming
  issues none. Download the file again after granting another organization or after a
  suspension. Deleting the plugin deletes them.
- Turning development mode off revokes nothing: the keys are refused while it is off, and work
  again if it is turned back on, until one of the events above.
- An `api_request` made with a development key has `detail.development` set to `true`, and is
  recorded in the key's organization like any other.
- The file holds keys and the plugin's secret settings. Keep it outside your plugin's source:
  `pack`, `validate` and the upload refuse a package that holds a key or a runtime file.

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
- **Models.** A service account cannot set or change where a model sends requests (`base_url`,
  `deployment_id`), on its own models or the organization's, and agent nodes always send to the
  model's endpoint. An import that carries a model endpoint is refused with `400`. A model's other
  fields stay editable with `llm_configs: update`.
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
| `api_request` | A service account's call that changed something; with its method, path (never the query string), route, status, the resource it created or named, and `created_count`; `development: true` when it was made with a [development key](#development-keys) | The plugin, and the person it acted for | The service account's |
| `package_approved` | A SuperAdmin approved a package (`version`, `trust`) | SuperAdmin | none |
| `grant_created` | A SuperAdmin granted the plugin to an organization | SuperAdmin | the grant's |
| `install_hook_succeeded`, `install_hook_failed` | The install hook reported (`job_id`, `attempt`, and `error` when it failed) | Platform | the grant's |
| `install_hook_retried` | A SuperAdmin retried a failed install hook (`job_id`) | SuperAdmin | the grant's |
| `grant_suspended` | A SuperAdmin suspended the plugin in the organization, or uninstalled it (`previous_state`, `purge_after`, `cause`: `grant` or `uninstall`) | SuperAdmin | the grant's |
| `grant_resumed` | A SuperAdmin resumed it, or reinstalled the plugin (`state`: `active`; `install_failed` when its install hook never succeeded; `upgrading` when the plugin's version changed meanwhile; `cause`: the suspension's) | SuperAdmin | the grant's |
| `grant_purge_started` | Deleting the plugin's data in the organization began (`reason`: `requested`, `grace_period_over` or `plugin_deleted`; `previous_state`; `owned_resources`, how many resources it owned) | SuperAdmin or Platform | the grant's |
| `grant_purged` | The plugin's data in the organization is deleted, and the grant with it | Platform | the grant's |
| `org_removed_hook_succeeded`, `org_removed_hook_failed` | The organization removed hook reported success, or failed for good after its retries (`job_id`, `attempt`, and `error` when it failed); a failed attempt that is retried records nothing | Platform | the job's |
| `org_removed_hook_retried` | A SuperAdmin retried a data removal (`job_id`) | SuperAdmin | the job's |
| `org_removed_hook_skipped` | A SuperAdmin skipped a data removal, or the platform did while deleting the plugin (`job_id`, `state_before`) | SuperAdmin or Platform | the job's |
| `plugin_uninstalled` | A SuperAdmin uninstalled the plugin (`purge_after`; `organizations`, how many grants it suspended) | SuperAdmin | none |
| `plugin_reinstalled` | A SuperAdmin reinstalled it (`organizations_resumed`) | SuperAdmin | none |
| `plugin_purge_started` | Deleting the plugin began (`reason`: `requested` or `grace_period_over`) | SuperAdmin or Platform | none |
| `plugin_removal_failed` | The plugin node reported that removing the plugin failed (`error`) | Platform | none |
| `plugin_removal_retried` | A SuperAdmin asked the node to try the removal again | SuperAdmin | none |
| `plugin_purged` | The plugin is deleted (`version`, `had_database`) | Platform | none |
| `settings_changed` | A SuperAdmin changed settings (the keys only, never values) | SuperAdmin | none |
| `limits_changed` | A SuperAdmin changed limit overrides (the overrides in force afterwards, one key per limit, such as `memory_mb` and `cpu_priority`) | SuperAdmin | none |
| `restarted` | A SuperAdmin restarted the backend (`restart_generation`) | SuperAdmin | none |
| `database_ready` | The plugin's database is ready: the first time, again after a failure, and after new migrations ran (`migrations_applied`, the number of migrations applied so far) | Platform | none |
| `database_failed` | Setting up the plugin's database failed (`error`); recorded when it starts failing, not again while it keeps failing | Platform | none |
| `database_limit_restored` | The plugin node put back a database limit the plugin's role had changed (`setting`: `statement_timeout`); at most once an hour | Platform | none |
| `plugin_upgrade_started` | A SuperAdmin approved a newer version (`from_version`, `to_version`, `access_growth_acknowledged`, `untrusted_acknowledged`; `replaced_version` when it took a failed version's place) | SuperAdmin | none |
| `plugin_maintenance_started` | The plugin went offline for its upgrade (`to_version`; `organizations`, how many went offline) | Platform | none |
| `plugin_upgrade_failed` | The upgrade failed (`to_version`, `stage`, `step`, `error`) | Platform | none |
| `plugin_upgrade_retried` | A SuperAdmin retried the failed upgrade (`to_version`) | SuperAdmin | none |
| `plugin_upgrade_cancelled` | A SuperAdmin cancelled the upgrade (`to_version`, `stage`) | SuperAdmin | none |
| `plugin_upgraded` | The new version runs (`from_version`, `to_version`, `maintenance_seconds`) | Platform | none |
| `database_backed_up` | The plugin node backed up the database (`file_name`, `reason`: `pre_upgrade` or `pre_restore`, `size_bytes`, `version`) | Platform | none |
| `database_restore_requested` | A SuperAdmin asked to restore a backup (`file_name`) | SuperAdmin | none |
| `database_restored`, `database_restore_failed` | The restore finished (`file_name`, `pre_restore_file_name`), or failed (`step`, `error`) | Platform | none |
| `upgrade_hook_succeeded`, `upgrade_hook_failed` | The upgrade hook reported (`job_id`, `attempt`; `from_version` and `to_version` on success; `error` and `next_attempt_at` on failure, `next_attempt_at` null once the automatic retries are used up) | Platform | the grant's |
| `upgrade_hook_retried` | A SuperAdmin retried a failed upgrade hook (`job_id`) | SuperAdmin | the grant's |
| `development_target_set` | A SuperAdmin set or changed where development mode serves the plugin from (`backend_port`, `spa_port`) | SuperAdmin | none |
| `development_target_cleared` | A SuperAdmin stopped development (`revoked_keys`, how many development keys stopped working) | SuperAdmin | none |
| `development_runtime_file_issued` | A SuperAdmin downloaded the development runtime file (`organizations`, how many organizations it holds a key for); the file itself is never recorded | SuperAdmin | none |

Events name the plugin by its identifier and the organization by its id, so they outlive the
plugin, its grants and the organization. Once an organization is deleted, only SuperAdmins see its
events, on the plugin's **Activity** tab. Logins to the plugin are not activity, and neither are runs refused while the plugin is suspended. An event's `detail` holds
only numbers, text, booleans and lists of text. `request.route` is the URL path pattern of the
endpoint, the same form for every endpoint: `api/graphs/<pk>/`, `api/sessions/<session_id>/stop/`.

## Errors

| Code | Status | When |
|---|---|---|
| `service_account_not_authenticated` | 401 | The key is unknown, revoked or replaced more than 10 minutes ago, its grant holds no key, its organization is inactive, or the call did not come through the plugins network; for a [development key](#development-keys), development mode is off or the call did not come through the development API listener; for any other key, the call came through the development API listener |
| `invalid_on_behalf_of` | 400 | A malformed `X-EpicStaff-On-Behalf-Of` |
| `on_behalf_of_not_allowed` | 403 | The person may not use the plugin in the organization |
| `organization_not_found` | 404 | `X-Organization-Id` names another organization |
| `permission_denied` | 403 | The declared access does not cover the call, or only people use the endpoint |
| `person_not_found` | 404 | The people endpoint, for anyone who may not use the plugin |
| `invalid` | 400 | A malformed people lookup |
| `throttled` | 429 | Over `requests_per_minute` |

Every code is in [Error codes](error-codes.md).
