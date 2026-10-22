# Error codes

Every error EpicStaff's plugin API returns uses EpicStaff's error envelope:

```json
{ "status_code": 400, "code": "invalid_plugin", "message": "The plugin package is invalid. 2 problems found.",
  "errors": [ { "loc": "manifest.limits.memory_mb", "message": "asks for 2048; this EpicStaff allows at most 1024" } ] }
```

`code` is stable; `message` is for people and may change. `errors` is present on codes that list
problems; each `loc` is a dotted path with list indexes, prefixed by the part it refers to
(`package.`, `contents.`, `signature.`, `manifest.`, `plugins[…]`, `values.`, `overrides.`,
`report.`), or the name of a login parameter or body field. A submitted value is never echoed
back.

## Plugin API codes

| Code | Status | When |
|---|---|---|
| `invalid_plugin` | 400 | The package breaks a format, layout or manifest rule, declares access this EpicStaff's permission catalog does not have, asks for more than the platform maximums, or holds nothing to install. `errors` lists each problem |
| `invalid_signature` | 400 | The package is signed, but the signature names another package or does not verify with the trusted key it claims |
| `package_too_large` | 413 | The upload is larger than `PLUGINS_MAX_PACKAGE_MB` |
| `plugin_upgrade_unavailable` | 409 | The package cannot upgrade the installed plugin: it drops the backend or the database, or changes a migration file that is already applied. `errors` says which, with `loc` `manifest.backend`, `manifest.database` or `package.database/migrations/<name>`. See [compatibility and versioning](compatibility-and-versioning.md) |
| `plugin_version_not_newer` | 409 | Uploading or approving a version that is not newer than the plugin's latest approved version (the version being installed by an open upgrade, else the installed one): the same version, an older one, or one that differs only in build metadata. The body also has `installed_version` and `latest_version`; `message` names both |
| `plugin_not_upgradable` | 409 | Approving a newer version while the plugin's state allows no upgrade: it is still provisioning, another upgrade is working, or a restore of its database runs |
| `review_outdated` | 409 | Approving an upgrade without `reviewed_against_package_id`, or naming another package than the version the new one is now compared with. Load the review again |
| `access_growth_not_acknowledged` | 400 | Approving an upgrade whose new version asks for new access without `access_growth_acknowledged: true` |
| `upgrade_not_cancellable` | 409 | Cancelling an upgrade that is not open, that adds a backend, whose database restore runs, or whose database already holds a migration of the new version (restore the backup first) |
| `upgrade_not_retryable` | 409 | Retrying an upgrade that has not failed, or with none open, or while a restore of its database runs |
| `plugin_upgrade_open` | 409 | Uninstalling a plugin while an upgrade is open (cancel it, or delete the plugin), or restarting a plugin stopped for its upgrade |
| `backup_not_found` | 404 | A backup that does not exist, is another plugin's, or whose file the plugin node no longer holds |
| `restore_not_allowed` | 409 | Restoring outside a failed migration or start of the open upgrade, while another restore runs, or a backup this upgrade did not take or whose file no longer matches its sha256 |
| `invalid_restore_phrase` | 400 | Restoring a backup with a `verification_phrase` that is missing or not exactly `restore-<plugin id>`. Checked after `backup_not_found` and `restore_not_allowed`, before anything changes |
| `upgrade_not_found` | 404 | A plugin node asks to advance an upgrade that does not exist or is another node's |
| `upgrade_not_current` | 409 | A plugin node asks to advance an upgrade that is over, has failed, or is not in the stage before the one asked for |
| `invalid_upgrade_advance` | 400 | A plugin node's request to advance an upgrade without the backup it needs, with a backup of another installation, upgrade, reason or version, with another backup than the one recorded, or with one whose sha256 is not the recorded one (`loc` `advance.backup.sha256`); also a body that does not follow the format. `loc` is under `advance`. Checked after `upgrade_not_found` and `upgrade_not_current` |
| `plugin_uninstalling` | 409 | Uploading a package for, approving a package of, or restarting a plugin that is uninstalled or being deleted; suspending, resuming, or retrying the install or upgrade hook of a grant of such a plugin; or changing the settings or limits of a plugin being deleted (they stay editable while it is uninstalled) |
| `plugin_package_not_found` | 404 | No such package; for a plugin node, a package that is neither the current package nor an open upgrade's target of one of its placements |
| `package_not_pending` | 409 | Approve or reject of a package that was already decided |
| `untrusted_not_acknowledged` | 400 | Approve of an untrusted package without `untrusted_acknowledged: true` |
| `plugin_not_found` | 404 | No plugin with this identifier, a deleted plugin included (its activity is still served); on the public endpoints and the login endpoints, a plugin that is neither running nor stopped for an upgrade; on the login endpoints (`plugin-authorize`, `login-organizations`), also a plugin without a backend, which nobody can log in to |
| `plugin_not_running` | 409 | A grant for a plugin that is not running (a plugin with a backend runs once its node reports it healthy); in plugin development mode, also setting development ports or downloading the development runtime file of a plugin that is not running |
| `plugin_already_granted` | 409 | The organization already has a grant for the plugin |
| `organization_inactive` | 409 | A grant to a deactivated organization |
| `package_file_mismatch` | 409 | The stored package file is missing or is not the file that was reviewed; reject it and upload again |
| `invalid_plugin_role_permissions` | 400 | A Roles-matrix write names a plugin that is not running and granted in the role's organization (or names it twice), or lists actions the plugin does not declare, repeats one, or gives any without `read`. `loc` is `plugins[<i>].plugin_identifier` or `plugins[<i>].actions` |
| `plugin_has_no_backend` | 409 | Settings, limits, runtime or restart of a plugin whose node package has no backend: the current package, or an upgrade's target once the plugin is stopped for it; also downloading the development runtime file of such a plugin, since there is no backend to develop |
| `plugin_development_mode_off` | 409 | Setting development ports or downloading the development runtime file while plugin development mode is off on this deployment (`PLUGINS_DEV_MODE=false`). Stopping development still works |
| `invalid_plugin_settings` | 400 | A settings write with an unknown key, a value of the wrong type or size, or clearing a required setting that has no default. `loc` is `values.<key>`. On an upgrade's approval, also a setting the new version needs that is still missing or invalid; `loc` is `settings.<key>` |
| `invalid_plugin_limits` | 400 | A limits write with an unknown limit, a value that is not a positive integer or would raise the limit, or a `cpu_priority` other than `low`. `loc` is `overrides.<key>` |
| `no_plugin_node` | 409 | Approving a package with a backend while no node named `PLUGINS_NODE_NAME` is registered: EpicStaff registers it at start-up (`manage.py seed_plugin_node`), so it has not started with plugins on since the node was configured, or `PLUGINS_NODE_NAME` changed |
| `plugin_node_full` | 409 | Approving a package with a backend while every port or Unix user id of the plugin node is taken |
| `no_plugin_database_server` | 409 | Approving a package with a `database` while no plugin database server is registered: EpicStaff registers it at start-up while plugins are on (`manage.py seed_plugin_node`), so EpicStaff has not been started with `PLUGINS_ENABLED=true` since the plugin database server was added |
| `node_not_authenticated` | 401 | A plugin node request without the node key, or with a wrong one |
| `placement_not_found` | 404 | A plugin node asks for the runtime credentials of a placement that is not its own |
| `invalid_node_report` | 400 | A plugin node report that does not follow the report format (fields this EpicStaff does not know are ignored). `loc` is under `report` |
| `signing_key_missing` | 503 | No plugin signing key exists yet, so no context can be signed; EpicStaff creates the first one at start-up with plugins on (`manage.py seed_plugin_node`) |
| `invalid` | 400 | A request body or query of the wrong shape, such as a missing `org_id`, a people lookup without 1 to 100 distinct positive user ids, or an unknown `action` filter on plugin activity. On the [token exchange](token-exchange.md), the body is not exactly `{"code", "code_verifier"}` with each value of its form, or is not JSON; `errors` lists each problem, `loc` being the field, an unknown key, or `body` |
| `invalid_authorize_request` | 400 | A [plugin login](token-exchange.md) authorize request with a missing, repeated or malformed parameter, or one the protocol does not name (such as `redirect_uri` or `return_path`). Answered as JSON, never as a redirect; `loc` is the parameter's name |
| `invalid_grant` | 400 | A token exchange whose code is unknown, expired (codes live 60 s) or already used, whose `code_verifier` does not match the code's challenge, that does not come from the plugin's own origin, or whose person changed their password after the code was issued. A failed exchange still uses up the code |
| `plugin_access_denied` | 403 | A token exchange for a person who lost access to the plugin in that organization after the code was issued, or for a plugin that stopped running since |
| `plugin_origin_refused` | 403 | A request from a plugin page (an `Origin` in the plugins base domain) to anything but the token exchange, `/api/plugin-public/*` included: plugin pages cannot call EpicStaff's API. The authorize navigation is not refused. Also a request with `Origin: null` to any `/api/auth/` endpoint or the password-change confirm, other than `GET`, `HEAD` and `OPTIONS`. See [what a plugin page cannot do](token-exchange.md#what-a-plugin-page-cannot-do) |
| `service_account_not_authenticated` | 401 | A plugin backend's `Authorization: PluginKey <key>` that EpicStaff does not accept: an unknown, revoked or replaced key (a replaced key works for 10 minutes after the next one is minted), a key whose organization is inactive or whose grant does not hold keys (only `granting`, `active` and `upgrading` do), or a request that did not come through the plugins network. Comes with `WWW-Authenticate: PluginKey` on the `/api/plugin-runtime/` endpoints. Read the key from the runtime file again and retry once; see the [service account API](service-account-api.md) |
| `invalid_on_behalf_of` | 400 | `X-EpicStaff-On-Behalf-Of` is not a user id: a decimal positive whole number below 2^63 |
| `on_behalf_of_not_allowed` | 403 | The person `X-EpicStaff-On-Behalf-Of` names may not use the plugin in the service account's organization: unknown, deactivated, no member, no `read` on the plugin, or the grant is not active (always while the install hook runs). One answer for every reason |
| `person_not_found` | 404 | The people endpoint: the user may not use the plugin in the service account's organization, members without `read` included |
| `grant_not_found` | 404 | Suspending, resuming, deleting the data of, or previewing a suspension or deletion of a grant, or retrying its install hook, when the grant does not exist or is another plugin's |
| `hook_not_retryable` | 409 | Retrying the hook of a grant whose install or upgrade hook has not failed |
| `grant_not_suspendable` | 409 | Suspending a grant that is already suspended, or in a state that cannot be suspended. Reload the grant: its `allowed_actions` lists what it allows |
| `grant_not_suspended` | 409 | Resuming a grant that is not suspended |
| `grant_not_purgeable` | 409 | Deleting the data of a grant whose data, or whose plugin, is already being deleted |
| `invalid_purge_phrase` | 400 | Deleting a grant's data or a plugin with a `verification_phrase` that is missing or not exactly the one the preview shows (`purge-<plugin id>-<organization name>`, `purge-<plugin id>`). A name changed since the preview changes the phrase: reload it. Checked after `…_not_found` and the conflicts, before anything changes |
| `plugin_not_uninstallable` | 409 | Uninstalling a plugin that is not provisioning, running or failed |
| `plugin_not_uninstalling` | 409 | Reinstalling a plugin that is not uninstalled |
| `plugin_not_purgeable` | 409 | Deleting a plugin that is uploaded (reject it instead) or already being deleted, or while a restore of its database runs |
| `removal_not_retryable` | 409 | Retrying the removal of a plugin whose plugin node has not reported the removal failed |
| `org_removed_hook_not_retryable` | 409 | Retrying a data removal (an organization removed hook) that is running, finished, or due already |
| `org_removed_hook_not_skippable` | 409 | Skipping a data removal that is running or finished |
| `plugin_suspended` | 409 | A flow run, test run, realtime conversation, voice call or code test-run would use something a plugin owns in the organization, and the plugin is not active there: suspended, still installing, its install failed, being upgraded, its upgrade failed, or its grant is gone. Every run of the organization's own flows that uses one of the plugin's resources is refused too. The body also has `plugin` (`identifier`, `name`) and `organization` (`id`); it never names the resource. See [the plugin lifecycle](../explanation/lifecycle.md) |
| `hook_job_not_found` | 404 | A plugin node claims or reports a hook job that does not exist or belongs to another node; a SuperAdmin retries or skips a data removal that does not exist, is another plugin's, or is not a data removal |
| `hook_job_not_claimable` | 409 | A plugin node claims a hook job that is not waiting or not due yet, or that its kind's rules do not let run now: an install hook whose plugin is not running or whose grant is gone or has moved on; an upgrade hook whose plugin is not running or whose grant is not upgrading; an organization removed hook whose plugin is not running, uninstalled or being deleted, or whose grant is neither gone nor being deleted |
| `hook_job_not_running` | 409 | A plugin node reports the result of a hook job that is not running, or of another attempt than the running one |
| `invalid_hook_result` | 400 | A plugin node's hook result that does not follow the result format. `loc` is under `result` |

## Gateway codes

What a client of a plugin's own address (`https://<id>.<plugins base domain>/api/**`) gets when
the gateway refuses its request. The request never reaches the plugin.

| Code | Status | When |
|---|---|---|
| `login_required` | 401 | The path is not one of the plugin's [public paths](../how-to/public-paths.md), and the request carries no acceptable plugin login token: none, a malformed, expired or another plugin's token, or one whose person is deactivated or changed their password; also, for a person still a member of the organization, one whose grant was suspended or re-created. Comes with `WWW-Authenticate: Bearer`. The JS SDK renews the token once and retries |
| `not_found` | 404 | No running plugin with a backend has this address, or the path is not canonical (dot segments, encoded dots, doubled slashes, a path into the platform's own `/_epicstaff/` paths) |
| `rate_limited` | 429 | The client went over the public path's `rate_limit_per_minute`. Comes with `Retry-After: 60` |
| `request_too_large` | 413 | The body is larger than the public path's `max_body_kb`, or its size is not declared (a chunked body, or a `POST`, `PUT`, `PATCH` or `DELETE` without `Content-Length`) |
| `plugin_unavailable` | 503 | The plugin is installed but its process is not running and healthy right now, or EpicStaff cannot sign a context yet; for a member of an organization whose upgrade failed, every path that is not public. Comes with `Retry-After: 30` |
| `plugin_maintenance` | 503 | The plugin is stopped for an upgrade: every path, public ones included. Also, once the plugin is back, a path that is not public for a member of an organization whose upgrade hook has not finished. Comes with `Retry-After: 30` and `X-EpicStaff-Gateway-Deny: maintenance`; the JS SDK reports `availability: maintenance` |
| `forbidden` | 403 | The token is valid, but its person may no longer use the plugin in its organization: their membership was removed, their role lost View, or the organization was deactivated. Someone no longer a member, or of a deactivated organization, gets this before any answer about the organization's grant, so they learn nothing of its suspension or upgrade. The JS SDK reports no access and does not retry |

A request that reaches the plugin process without a valid gateway context, which only happens
when something on the plugin node calls the process directly, is answered by the Python SDK with
`401 {"code": "context_invalid"}`; see the [gateway context](gateway-context.md).

## Codes from EpicStaff's API

The plugin endpoints also return EpicStaff's general codes:

| Code | Status | When |
|---|---|---|
| `not_authenticated` | 401 | No login, or an expired one |
| `permission_denied` | 403 | The caller may not use the endpoint: plugin administration by anyone but a SuperAdmin, any write with an API key, a Roles-matrix write without the right to edit roles in the organization, plugin activity without the Audit View permission, a service-account call that the plugin's declared `access` does not cover, or a service-account call to an endpoint that only people use ("Plugin service accounts cannot use this endpoint.") |
| `unsupported_media_type` | 415 | A package upload that is not `multipart/form-data`, or a token exchange that is not `application/json` |
| `throttled` | 429 | More than 120 token exchanges a minute from one client address, or a service account over its `requests_per_minute` ([Limits](limits.md)). Comes with `Retry-After` |
| `not_found` | 404 | A plugin activity event of another organization, or one that does not exist |
| `org_context_required` | 400 | The available-plugins list without `X-Organization-Id` |
| `org_membership_required` | 403 | The available-plugins list for an organization the caller is not a member of |
| `organization_not_found` | 404 | An organization that does not exist, or whose roles the caller may not read; for a service account, any organization but its own in `X-Organization-Id` |
| `role_not_found` | 404 | A role that does not exist, or a custom role of an organization whose roles the caller may not read |
| `built_in_role_immutable` | 403 | A Roles-matrix write on a built-in role: built-in roles always have the manifest defaults |
| `permission_escalation_denied` | 403 | A Roles-matrix write adding or removing an action the caller does not hold on that plugin themselves, or giving someone a role with such an action |

## Login callback errors

What the authorize step puts in the callback page's fragment (`#error=<code>&state=<state>`)
instead of a code. They are OAuth's words, not API codes; the JS SDK turns them into its login
states. See [token exchange](token-exchange.md).

| Code | When |
|---|---|
| `login_required` | No EpicStaff session, on a silent request (`prompt=none`). Without `prompt` the browser goes to EpicStaff's login page instead |
| `access_denied` | The person may use the plugin in no organization, or not in the one named by `org` |
| `interaction_required` | The person may use the plugin in several organizations and none was named, on a silent request. Without `prompt` the browser goes to EpicStaff's organization chooser instead |
| `temporarily_unavailable` | The person may use the plugin once an upgrade finishes: the plugin is stopped for its upgrade, or their organization's upgrade has not finished. The JS SDK reports `availability: maintenance` |
