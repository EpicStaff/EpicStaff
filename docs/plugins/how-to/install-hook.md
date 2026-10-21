# Write an install hook

An install hook sets your plugin up in an organization when a SuperAdmin grants it: it creates
the flows, files and other EpicStaff resources the plugin needs there, before anyone in the
organization opens it. The [Hook API](../reference/hook-api.md) is the contract; this page
builds one with the Python SDK, the way the Weather sample does
(`plugin-samples/weather/backend/src/weather_plugin/install_hook.py`).

## 1. Ask for it in the manifest

```json
"hooks": { "install": true, "timeouts_seconds": { "install": 300 } },
"access": [
    { "resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Creates the Weather forecast flow and runs it for you." },
    { "resource_type": "files", "actions": ["read", "create"], "reason": "Stores the Weather readme in your organization's storage." }
]
```

The hook can do only what `access` declares, and the SuperAdmin approves that list when they
approve the package. Declare the actions your hook's calls need, including `read` for its
lookups, and `flows: use` if it creates a schedule, webhook or Telegram trigger.

## 2. Register a handler

Register one async function on the SDK's hook registry, in a module your entrypoint module
imports, so it is registered by the time the runner starts:

```python
from epicstaff_plugin.client import OrgClient
from epicstaff_plugin.contracts.hook_api import HookRequest
from epicstaff_plugin.hooks import hook_registry


@hook_registry.on_install
async def install(request: HookRequest, epicstaff: OrgClient) -> None:
    await ensure_forecast_flow(epicstaff)
    await ensure_readme(epicstaff)
```

In the Weather sample, `weather_plugin/app.py` (the entrypoint `weather_plugin.app:app`) does
`from weather_plugin import install_hook` for that reason.

The handler gets:

- `request`: the verified call, with `request.org.id`, `request.org.name`, `request.job_id` and
  `request.attempt`;
- `epicstaff`: an `OrgClient` for that organization, calling EpicStaff as your plugin alone
  ([Call EpicStaff from your backend](call-epicstaff-from-the-backend.md)).

Returning succeeds the hook. Raising fails it, and the first line of the exception is the error
the SuperAdmin sees next to the grant. An `EpicStaffApiError` already reads well there, for
example `EpicStaff refused POST graphs/: 403 permission_denied: You do not have permission to
perform this action.`

`hook_registry.on_upgrade` and `hook_registry.on_org_removed` register the other kinds the same
way; EpicStaff does not call them yet.

## 3. Make it safe to run again

A failed hook is retried with the same `job_id`, and an attempt can fail halfway. Write every
step so that running it again only finishes what is missing:

```python
async def ensure_readme(epicstaff: OrgClient) -> None:
    try:
        await epicstaff.get("storage/info/", params={"path": "weather/README.md"})
        return
    except EpicStaffApiError as error:
        if error.status != 404:
            raise
    await epicstaff.upload_file("weather", "README.md", README_TEXT.encode("utf-8"))
```

The Weather sample finds its flow by a tag it writes into the flow's description
(`graph-light/?search=…`), creates it if it is missing, and fills it in one bulk save
(`graphs/<id>/save/`), which EpicStaff applies in one transaction: an attempt that fails before
the save leaves an empty flow, and the next attempt fills it. Find what your hook made by a mark
of your own, not by a name alone: a person may already have a flow of that name, and adopting
it would change their work. Flow names are unique in an organization, so the sample names its
flow "Weather forecast (Weather plugin)" when a person's flow already has the plain name. A plugin with a database of its own can record what it made under the `job_id`
instead.

## 4. Test it

`epicstaff_plugin.testing.HookSigner` signs hook calls as EpicStaff does, and an
`httpx.MockTransport` stands in for EpicStaff's API:

```python
import httpx
from epicstaff_plugin.client import EpicStaffClient
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import (
    ContextSigner,
    HookSigner,
    service_account_key,
    write_runtime_file,
)
from fastapi.testclient import TestClient
from weather_plugin.app import app


def test_the_install_hook_succeeds(tmp_path):
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.4.0")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(
        runtime_file,
        signer=signer,
        service_accounts={
            "3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "granting"}
        },
    )
    runtime = RuntimeConfig.load(runtime_file)
    epicstaff = EpicStaffClient(runtime, transport=httpx.MockTransport(fake_epicstaff_api))
    client = TestClient(build_app(app, runtime, epicstaff=epicstaff))

    call = HookSigner(signer).call("install", org={"id": 3, "name": "Acme"}, job_id=41)
    response = client.post(call.path, headers=call.headers, content=call.body)

    assert response.json() == {"status": "done"}
```

Call it twice, and once with an earlier attempt half done, and check that nothing is created
twice. The Weather sample's tests (`src/plugin_sdk/tests/test_weather_sample_backend.py` in the
EpicStaff repository) do all three against an in-memory fake of the API.

## 5. Watch it run

After the SuperAdmin grants the plugin, the organization's row in the plugin's Grants table
shows "Installing…" and then "Active", or the hook's error with a "Retry install" button. The
plugin's Activity tab lists every write the hook made and the hook's outcome.
