# The plugin lifecycle in an organization

A SuperAdmin grants a plugin to an organization, and can suspend it there and resume it. This
page explains the states a plugin goes through in one organization, what a suspension stops and
what it does not, and what plugin authors should do about it.

## States

| State | Shown as | What it means |
|---|---|---|
| `granting` | Waiting for the plugin to start, then Installing… | The plugin was granted and its install hook has not finished. Its service account holds a key, so the hook can call EpicStaff, but people cannot open the plugin yet |
| `active` | Active | People with the plugin's View open it from the left bar, and its backend acts in the organization |
| `install_failed` | Install failed | The install hook failed. The SuperAdmin can retry it ("Retry install") |
| `suspended` | Suspended | A SuperAdmin suspended the plugin in this organization. Nothing it owns there runs, and its data is kept until the date shown |

A plugin without an install hook is `active` as soon as it is granted. The plugin's other
organizations are not affected by anything that happens in this one: a suspended plugin's
process keeps running for them.

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
keep using them. Repoint them in **Settings → Default models**.

## What a suspension does not stop

- **AI features outside runs**, such as the flow assistant, decision-table explanations,
  knowledge indexing, and the "test" actions of models and tools.
- **Registering a webhook or a Telegram bot** with a Secret the plugin owns.
- **Resources a step reaches by name** through EpicStaff's API while it runs, for example a
  key-value table that Python code reads by its id.
- **Voice conversations already open.** New ones are refused. A voice call can also still
  connect for a short while if the realtime service looked the channel up just before the
  suspension.

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
before then restores everything. This version does not delete it yet when the date passes.

## For plugin authors

- A suspended organization disappears from the runtime file's `service_accounts`, and the
  Python SDK raises `ServiceAccountUnavailable` for it
  ([Call EpicStaff from your backend](../how-to/call-epicstaff-from-the-backend.md)).
- No hook is called on suspend or resume. Stop your per-organization background work when the
  organization leaves the runtime file, and start it again when it comes back.
- Until your install hook succeeds, runs that use what the plugin owns in the organization are
  refused ([Write an install hook](../how-to/install-hook.md)).
- Every code is in [Error codes](../reference/error-codes.md).
