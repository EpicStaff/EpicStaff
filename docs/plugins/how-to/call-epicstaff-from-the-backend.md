# Call EpicStaff from your backend

A plugin backend calls EpicStaff's API as the plugin's **service account** in an organization:
to create flows, run them, store files, read who someone is. It does so alone, or **on behalf of**
a person who is using the plugin. This page shows how, with `epicstaff_plugin.client`.

## Service accounts and declared access

Every organization a plugin with a backend is granted to gets a service account for it. Its key
is in the [runtime file](../reference/runtime.md#service-accounts), one per organization, and
the SDK reads it for you.

What a service account may do is exactly the manifest's `access`, which the SuperAdmin approved:

```json
"access": [
    { "resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Creates the Weather forecast flow and runs it for you." },
    { "resource_type": "files", "actions": ["read", "create"], "reason": "Stores the Weather readme in your organization's storage." }
]
```

The resource types and actions are those of EpicStaff's permission catalog
(`GET /api/permissions/catalog/` lists them; [Declare access](declare-access.md) explains how to
choose). A call outside the declared access gets 403
`permission_denied`, and a service account never reaches another organization: a call naming
one gets 404. `organizations`, `memberships`, `roles`, `api_keys`, `audit` and `chats` cannot be
declared, and some surfaces refuse service accounts altogether: key management, the
administration pages, flow assistants, realtime sessions, notification email, favorites and
audit filter presets.

Everything a service account creates is recorded as owned by the plugin, and every change it
makes appears in the organization's Plugin activity, which Org Admins read.

The key works only on the address the runtime file names, `epicstaff_api_url`: EpicStaff's
internal address, from the plugin network, or for a
[development backend](../reference/runtime.md#a-development-backend) the development API listener
on the developer's machine. On EpicStaff's public address it gets 401. Never log it, and never
send it anywhere else.

## The client

```python
from epicstaff_plugin.client import EpicStaffClient

epicstaff = EpicStaffClient()  # this process's runtime file; one per process
acme = epicstaff.for_org(3)

flows = await acme.get("graph-light/", params={"search": "Weather forecast"})
created = await acme.post("graphs/", {"name": "Weather forecast"})
```

- Paths are relative to EpicStaff's API: `graphs/` is `/api/graphs/`.
- `get`, `post`, `put`, `patch` and `delete` return the decoded JSON answer (`None` for an empty
  one); `request(method, path, ...)` returns the `httpx.Response` itself.
- Each call sends `Authorization: PluginKey <key>`, `X-Organization-Id: <org id>` and
  `Accept: application/json`, never goes through a proxy, never follows a redirect, and gives up
  after 30 seconds.
- An answer of 400 or more raises `EpicStaffApiError` with `status`, `code`, `message` and
  `errors` from EpicStaff's [error envelope](../reference/error-codes.md).
- An organization the runtime file holds no key for raises `ServiceAccountUnavailable`: the
  plugin is not granted there, its install hook failed, it is suspended there, or the node has
  not written the new runtime file yet.

**Keys rotate.** EpicStaff issues new keys every time the plugin process (re)starts and whenever
the plugin is granted to another organization; the previous key keeps working for 10 minutes.
The client reads the key from the runtime file on every call, and retries once with the new key
when EpicStaff answers 401 to a key that has since been replaced. Do not copy keys elsewhere.

**Suspension.** A SuperAdmin can suspend your plugin in one organization. Its key there stops at
once (401), the organization leaves the runtime file within seconds, so later calls raise
`ServiceAccountUnavailable`, and EpicStaff calls no hook. Treat the organization leaving the runtime file as
the signal: stop your per-organization background work for it, and start again when it comes
back. Meanwhile every run that uses something your plugin owns there is refused with 409
`plugin_suspended`, whoever starts it, the organization's people included: the error names your
plugin and the organization, never the resource. See [the plugin lifecycle](../explanation/lifecycle.md).

**Rate.** A service account may make the plugin's `requests_per_minute` calls per minute (see
[Limits](../reference/limits.md)); above it EpicStaff answers 429 `throttled` with
`Retry-After`.

## On behalf of a person

When a person uses your plugin and your backend acts for them, say so:

```python
@app.post("/api/forecast", status_code=202)
async def start_forecast(request: Request, context: UserContext) -> dict[str, int]:
    person = epicstaff.client_for_context(context)  # their organization, on their behalf
    session_id = await person.run_flow(flow_id, {"city": "Paris"})
    return {"session_id": session_id}
```

`client_for_context(context)` is `for_org(context.org.id).on_behalf_of(context.user.id)`; it
refuses a public context. Its calls add `X-EpicStaff-On-Behalf-Of: <user id>`, and EpicStaff
then:

- checks that the person may use the plugin right now (an active member of the organization,
  holding the plugin's View); anyone else gets 403 `on_behalf_of_not_allowed`;
- records the person next to the plugin: on a run's principal ("Weather (plugin) on behalf of
  ada@…"), on the Plugin activity entry, and on the ownership record of what the call creates.
  The plugin owns what it creates, and the person is noted as whom it was created for; they
  never become its author or last editor.

EpicStaff checks **only your declared access** on these calls, never the person's own EpicStaff
rights: the person is asserted by your plugin, not proven to EpicStaff. So before you do
something for a person that they could not do in EpicStaff themselves, check their rights:

```python
person = await epicstaff.client_for_context(context).person(context.user.id)
if person is None or not person.has_epicstaff_permission("secrets", "create"):
    raise ApiError(403, "forbidden")
```

Your plugin's own permissions are in the gateway context (`context.has_permission("delete")`);
check those first.

## People

| Call | Answer |
|---|---|
| `await org.person(user_id)` | A `PluginPerson`, or `None` |
| `await org.people(user_ids)` | The `PluginPerson`s among them, sorted by id (asked in batches of 100) |
| `await org.me()` | A `ServiceAccountInfo`: the plugin, the organization, the grant's state, the declared access, the rate, and the person `X-EpicStaff-On-Behalf-Of` named |

A `PluginPerson` has `user` (`id`, `email`, `name`), `organization`, `plugin_permissions` (the
plugin actions they hold, always with `read`) and `epicstaff_permissions`: their own EpicStaff
rights from their role, in the shape of EpicStaff's `GET /api/permissions/me/`, every resource
type a key. `has_plugin_permission(action)` and `has_epicstaff_permission(resource_type, action)`
read them.

Only people who may use the plugin appear: active members of the organization who hold the
plugin's View. Everyone else is `None`, so your plugin never learns about people who cannot use
it. The client caches each answer for 30 seconds (`EpicStaffClient(person_cache_seconds=…)`, at
most 30, `0` turns it off); do not keep people longer than that.

## Flows and files

| Call | What it does | Needs |
|---|---|---|
| `await org.run_flow(graph_id, variables)` | Starts a run (`POST /api/run-session/`); returns the session id | `flows: use` |
| `await org.session(session_id)` | A `FlowSession`: `status`, `finished`, `succeeded`, and the run's final `variables` once it finished (`GET /api/sessions/<id>/`, from `status_data.variables`) | `flows: read` |
| `await org.wait_for_session(session_id, timeout=120, poll_seconds=2)` | Polls `session` until the run finished; raises `TimeoutError` | `flows: read` |
| `await org.upload_file(folder, filename, content)` | Stores bytes in the organization's storage (`POST /api/storage/upload/stream`) | `files: create`; `files: update` to replace a file |

A run's status is `pending`, `run` or `wait_for_user` while it goes, then `end` (succeeded),
`error`, `stop` or `expired`.

## Tests

Give the client an `httpx.MockTransport` and a runtime file with a key:

```python
import httpx
from epicstaff_plugin.client import EpicStaffClient
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.testing import service_account_key, write_runtime_file

write_runtime_file(
    path,
    service_accounts={
        "3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "active"}
    },
)
epicstaff = EpicStaffClient(RuntimeConfig.load(path), transport=httpx.MockTransport(answer))
```

The Weather sample's backend tests use an in-memory fake of every endpoint the sample calls.
