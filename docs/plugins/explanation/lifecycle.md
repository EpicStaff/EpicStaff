# The plugin lifecycle

A SuperAdmin grants a plugin to an organization, and can suspend it there and resume it. When a
suspension lasts longer than the grace period, or when the SuperAdmin asks for it, EpicStaff
deletes the plugin's data in that organization. A SuperAdmin can also uninstall a plugin from the
whole deployment, reinstall it within the grace period, or delete it for good. This page explains
the states a plugin goes through, what each step stops, keeps and deletes, and what plugin authors
should do about it.

## States

| State | Shown as | What it means |
|---|---|---|
| `granting` | Waiting for the plugin to start, then Installing… | The plugin was granted and its install hook has not finished. Its service account holds a key, so the hook can call EpicStaff, but people cannot open the plugin yet |
| `active` | Active | People with the plugin's View open it from the left bar, and its backend acts in the organization |
| `install_failed` | Install failed | The install hook failed. The SuperAdmin can retry it ("Retry install") |
| `suspended` | Suspended, or Suspended (plugin uninstalled) | A SuperAdmin suspended the plugin in this organization, or uninstalled it from the deployment. Nothing it owns there runs, and its data is kept until the date shown |
| `purging` | Deleting data | The plugin's data in the organization is being deleted; the row goes once that is done |

A plugin without an install hook is `active` as soon as it is granted. The plugin's other
organizations are not affected by anything that happens in this one: a suspended plugin's
process keeps running for them.

A plugin with a database gets it before its backend first starts: when its package is
approved, the plugin node creates the database and runs the package's migrations, then starts
the process ([Plugin database](../reference/database.md)). So the database is there for the
first install hook of every organization.

A pending install hook never times out. It waits for as long as the plugin's process is stopped,
failed or restarting, and runs once the process is healthy. A running hook fails when it
overruns its timeout. A SuperAdmin who gives up on a waiting install suspends the grant, which
fails the hook ("Suspended before the hook finished."), and then resumes it: the grant comes back
as "Install failed", with "Retry install".

## What a suspension stops

Suspending takes effect at once:

- **Keys.** Every key of the plugin's service account in the organization stops working, the
  one still inside its 10-minute overlap included. The organization leaves the plugin's
  runtime file within seconds, at the plugin node's next credentials fetch.
- **People.** The plugin leaves the left bar and the Roles matrix of the organization. The
  actions custom roles gave on it are kept, and come back on resume. A person's plugin login is
  refused within about 10 seconds: the gateway keeps its decision about a person for that long.
- **Runs.** Every run that uses anything the plugin owns in the organization is refused with
  409 `plugin_suspended`, whoever starts it, and whatever the flow: the plugin's own flows, and
  the organization's own flows that use one of the plugin's resources. That covers flow runs,
  test runs from a trigger node, realtime conversations, voice calls to a channel, and code
  test-runs. The answer names the plugin and the organization, never the resource.
- **Running sessions** of those flows are stopped.
- **Triggers** of those flows keep firing, and each time the run is refused: a schedule is
  refused at every tick (a one-time schedule that fires while suspended does not run later),
  and webhook and Telegram deliveries are refused. A refused trigger node is logged at most once
  a day for the same cause.

A run *uses* a resource the plugin owns when the flow reaches it in any way a run can: a node,
an agent with its LLM configs, default surfaces and voice configs, a surface's tools, knowledge
and files, a knowledge collection with every one of its RAGs' embedders and LLMs, a Secret that
code or a configuration declares, a file under a folder the flow attaches, a subflow, and so on.
The rule is deliberately broad, so it refuses some runs that would not have touched the
resource in the end; the preview shows exactly which ones.

Runs that use only the organization's own resources are never refused.

## The preview

"Suspend…" opens a preview before anything happens. It lists what the plugin owns in the
organization, the organization's flows that will stop (the ones that use something the plugin
owns), the plugin's own flows, the running sessions that will be stopped, the triggers that
will be refused, the realtime agents and voice channels that will be refused, the default-model
settings that point at the plugin's configurations, and the date until which the data is kept.

Default-model settings are not changed by a suspension: new agents and features outside runs
keep using them. The Agent LLM and Agent Function Calling LLM settings can be repointed in
**Settings → Default LLMs**; the preview also lists the other default-model settings that point
at the plugin's configurations, which that page does not show.

## What a suspension does not stop

- **AI features outside runs**, such as the flow assistant, decision-table explanations,
  knowledge indexing, and the "test" actions of models and tools.
- **Registering a webhook or a Telegram bot** with a Secret the plugin owns.
- **Resources a step reaches by name** through EpicStaff's API while it runs, for example a
  key-value table that Python code reads by its id.
- **Voice conversations already open.** New ones are refused. A voice call can also still
  connect for a short while if the realtime service looked the channel up just before the
  suspension.
- **The plugin's database and its outbound access.** Both belong to the plugin, not to one
  organization, and its process keeps running for its other organizations. The database keeps
  this organization's rows, and the process still reaches its declared hosts, but it no longer
  has a key for this organization, so it cannot act in it.

Outbound access ends within about 30 seconds of the plugin's process stopping, or of a host
leaving its allow-list ([Call the internet from your backend](../how-to/outbound-hosts.md)).

## Resume

"Resume" makes the grant `active` again, or `install_failed` if its install hook never
succeeded. People see the plugin again after a reload, custom roles keep their actions, and
runs work again. The old keys never work again: the plugin node's next credentials fetch,
within seconds, mints new ones and the organization is back in the runtime file. Resuming
calls no hook.

Granting the plugin to the organization again is not possible while it is suspended
(409 `plugin_already_granted`): resume it instead.

## Data kept until

A suspended plugin's data in the organization (its flows, files, secrets, configurations and
everything else it created there) is kept until the date the grants table shows as "Data kept
until": the day of the suspension plus `PLUGINS_GRACE_PERIOD_DAYS` (30 by default). Resuming
before then restores everything.

## When the grace period ends

Within about a minute of that date, EpicStaff begins deleting the plugin's data in the
organization, and the grant shows "Deleting data". Two things then happen side by side:

- **The plugin deletes its own data.** If its backend has an organization removed hook, EpicStaff
  asks the plugin to delete what it keeps for the organization, in its database and anywhere
  else ([Delete your data when an organization leaves](../how-to/org-removed-hook.md)).
- **EpicStaff deletes everything the plugin created in the organization**, including what it
  made on behalf of people: its flows, agents, surfaces, tools, files, knowledge collections,
  configurations, models, key-value tables, secrets, voice channels and webhook triggers. They do
  not go to the recycle bin: they are deleted for good, as if a person had deleted each one and
  emptied the bin.

The organization's own rows lose what they used, exactly as when a person deletes the item: an
agent loses the plugin's LLM config, a node loses its tool or file, and a default-model setting
that pointed at one of the plugin's configurations is emptied. The organization's flows
themselves stay. A resource that a row of another organization links to is not deleted, because
that delete would change the other organization's data: the grant shows the error, and EpicStaff
tries again every hour until the link is removed by hand. A flow with a running session waits
until the session ends.

The grant row goes once both are done: nothing the plugin created is left, and its organization
removed hook succeeded or was skipped. Its service account, keys and custom roles' actions go
with it. Until then, runs that use anything the plugin still owns there are refused, as while
suspended. The plugin can then be granted to the organization again, as a new grant.

## Delete data now

"Delete data…" on a grant deletes the plugin's data in that organization at once, in any state
but "Deleting data". It first shows what goes: what the plugin owns there, the organization's
flows that use it (they keep working without those parts), the plugin's own flows, the running
sessions that will be stopped, the default-model settings that will be cleared, and what happens
to the plugin's own data. It is irreversible, so it asks for a confirmation phrase,
`purge-<plugin id>-<organization name>`, typed exactly. A grant that is not suspended yet is
suspended first, without a separate "suspended" event, and deleting then goes on as when a grace
period ends.

## Uninstall and reinstall

"Uninstall…" takes a plugin out of service in every organization at once, and keeps its data:

- every grant that is active, being granted or whose install failed is suspended, with the cause
  "plugin uninstalled", until the plugin's own "Data kept until" date; a grant already suspended
  on its own keeps its own date;
- the plugin's process is stopped, and runs again only to call an organization removed hook;
- no path of the plugin is served any more, public paths included;
- a new version cannot be uploaded or approved, and the plugin cannot be restarted; its settings
  and limits stay editable, for a reinstall.

"Reinstall" before that date puts the plugin back: its backend starts again, and every grant the
uninstall suspended is active again, with its data. A grant that was suspended on its own stays
suspended. When the date passes, the plugin is deleted.

## Deleting a plugin

"Delete permanently…" deletes a plugin for good, from any state but uploaded, in maintenance or
already deleting. It asks for the phrase `purge-<plugin id>`. EpicStaff then:

1. deletes every organization's data, as when a grace period ends, the plugin's organization
   removed hook included;
2. once no grant, no waiting data removal and nothing the plugin owns is left, asks the plugin
   node to remove the plugin: the node stops its process, deletes its database and roles with
   every connection closed, and removes its code, environment, logs and files. **No backup is
   taken.** A database that another installation created is never deleted;
3. once the node reports it done, deletes the plugin's records, frontend files and packages. Its
   port and user id are given to another plugin only after that.

The plugin page shows the progress (organizations left, data removals waiting or failed, the
plugin node). The plugin's activity is kept, and stays readable for SuperAdmins. The same
identifier can then be installed again, as a new plugin with a new database.

## Deleting an organization

When an organization is deleted, everything EpicStaff holds for it goes with it, the plugin
grants and everything the plugins created there included. Each plugin with an organization
removed hook is asked to delete its own data for the organization; the delete report lists them
as "Plugin data". That request keeps the organization's id and name, and runs after the
organization is gone. The plugins' activity in the organization is kept, and only SuperAdmins see
it afterwards.

## Data removals: retries and skip

An organization removed hook that fails is retried after 1, 5 and 30 minutes, then every hour, for
7 days from its first attempt. After that it stays failed, and the plugin shows "Needs
attention". A SuperAdmin can retry a removal that waits or failed, and skip one that has not run
to the end: the plugin's data for that organization then stays where the plugin keeps it until
the plugin is deleted. A grant whose removal failed is not deleted until the removal is retried
or skipped; deleting the plugin skips failed removals by itself once no grant is left, because
its database goes next. The removals of deleted organizations are listed under "Deleted
organizations".

## With plugins switched off

Grace periods are a promise about EpicStaff's data, so they are kept whatever `PLUGINS_ENABLED`
says: EpicStaff still deletes the plugins' resources when a grace period ends, and still refuses
runs that use what a plugin owns. The plugins' own data waits until plugins run again: their
organization removed hooks run once the plugin node does.

## For plugin authors

- A suspended organization disappears from the runtime file's `service_accounts`, and the
  Python SDK raises `ServiceAccountUnavailable` for it
  ([Call EpicStaff from your backend](../how-to/call-epicstaff-from-the-backend.md)).
- No hook is called on suspend, resume, uninstall or reinstall. Stop your per-organization
  background work when the organization leaves the runtime file, and start it again when it
  comes back.
- When an organization's data must go, your organization removed hook is called, with no key for
  the organization ([Delete your data when an organization leaves](../how-to/org-removed-hook.md)).
- What installing a plugin means for its operators is in [Accepted risks](accepted-risks.md).
- Until your install hook succeeds, runs that use what the plugin owns in the organization are
  refused ([Write an install hook](../how-to/install-hook.md)).
- Every code is in [Error codes](../reference/error-codes.md).
