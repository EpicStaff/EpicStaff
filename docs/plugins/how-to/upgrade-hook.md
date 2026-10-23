# Write an upgrade hook

When a SuperAdmin upgrades your plugin to a new version, EpicStaff runs the new version's
migrations, starts its process, and then asks your backend to bring each organization to the
new version: create what the new version needs in EpicStaff, change what an earlier version
made. That request is the **upgrade hook**. This guide builds one with the Python SDK, after
the Weather sample. The [Hook API](../reference/hook-api.md#what-happens-on-an-upgrade) is the
reference, and [Compatibility and versioning](../reference/compatibility-and-versioning.md) says
what a new version may change.

## 1. When it runs

EpicStaff calls the hook once per organization:

- after the new version has started, for every organization that was using the plugin;
- when a suspended organization is resumed, if the plugin's version changed meanwhile;
- again, with a newer version, for every organization whose upgrade hook failed.

The new version's database migrations have all run by then, and the new process is the one
answering. Each organization waits as "Upgrading…" until its hook succeeds, and nobody in it can
use the plugin in the meantime: it is off until its hook succeeds.

## 2. Ask for it in the manifest

```json
"hooks": { "install": true, "upgrade": true, "org_removed": true }
```

The hook needs a `backend`. It may take up to 30 minutes, the platform maximum; a shorter limit
goes in `"timeouts_seconds": { "upgrade": 600 }`. Declare it in the version that needs it: the
new version's manifest decides whether its upgrade runs a hook. Without `"upgrade": true`, each
organization goes straight back to "Active" once the new version runs.

## 3. Register a handler

Register one async function that takes the request and an `OrgClient`, like the install hook.
The Weather sample's is in `plugin-samples/weather/backend/src/weather_plugin/upgrade_hook.py`:

```python
@hook_registry.on_upgrade
async def upgrade(request: HookRequest, epicstaff: OrgClient) -> None:
    """Bring the organization's flow and readme to this version, unless it already has them."""
    previous_version = request.previous_version
    if previous_version is not None and not is_newer(FLOW_VERSION, previous_version):
        return
    await ensure_forecast_flow(epicstaff)
    await ensure_readme(epicstaff)
```

`plugin-samples/weather/backend/src/weather_plugin/app.py`, the entrypoint module, imports it so
it is registered by the time the runner starts. The client acts as your plugin alone, with the
organization's service account, exactly as in the install hook.

## 4. Bring an organization from any earlier version

`request.previous_version` is the version the organization was last brought to. Do not assume
it is the version before this one:

- an organization whose upgrade hook failed, or that was suspended, skips the versions in
  between, so it may be several versions back;
- it may name a version without a backend, which ran no hook at all;
- it is `null` for an organization that never finished installing an earlier version.

So write the hook to bring an organization from any earlier version. The simplest way is the
Weather sample's: run the install hook's steps again. They create what is missing, and bring
what an earlier version made to this version
(`plugin-samples/weather/backend/src/weather_plugin/forecast_flow.py` gives the forecast flow
this version's description and code). Treat `null` as a fresh install.

Compare versions with `epicstaff_plugin.versions`, never as text: `"0.10.0"` is newer than
`"0.9.0"`, and `"0.7.0-rc.1"` is older than `"0.7.0"`. The sample keeps the version that last
changed its flow in one constant, `FLOW_VERSION`, and skips organizations already at it or later.

## 5. Make it safe to run again

A failed hook is retried with the same `job_id`, and an attempt can fail halfway. A later
version's hook may also find what this one made. Write every step so that running it again only
finishes what is missing: look up what is there, compare it with what this version wants, and
change only what differs. The Weather hook makes no call that changes anything for an
organization whose flow is already this version's.

## 6. While it runs

Until the hook succeeds, the organization's `grant_state` in the runtime file is `upgrading`. Its
service account holds a key, so your hook can call EpicStaff, but the organization is not using
the plugin yet: do background work for an organization only while its `grant_state` is
`active`. The Weather sample's hourly purge works across organizations in its own database, and
needs no organization's key.

Runs that use something your plugin owns in the organization are refused while it upgrades
("… which is being upgraded in this organization"). Sessions that were already running finish.

## 7. When it fails

Raise to fail the hook: the first line of the exception is what the SuperAdmin reads next to
the organization. A backend that does not answer, times out, or has no handler (`501`) fails it
too. EpicStaff then tries again by itself, 1 minute after the first failure and 5 minutes after
the second. After a third failure in a row the organization's upgrade has failed: it stays off,
and the plugin shows "Needs attention". The SuperAdmin can then:

- **Retry** it on the organization's row, which starts a new series of attempts;
- upload a newer version that fixes the hook: once it has upgraded the plugin, every
  organization whose hook failed gets the new version's hook.

## 8. Test it

`epicstaff_plugin.testing.HookSigner` signs hook calls as EpicStaff does, and an
`httpx.MockTransport` stands in for EpicStaff's API. Give the organization the `upgrading` grant
state, as EpicStaff does while the hook runs:

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


def test_the_upgrade_hook_brings_an_organization_from_0_6_0(tmp_path):
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.7.0")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(
        runtime_file,
        signer=signer,
        service_accounts={
            "3": {"key": service_account_key(), "org_name": "Acme", "grant_state": "upgrading"}
        },
    )
    runtime = RuntimeConfig.load(runtime_file)
    epicstaff = EpicStaffClient(runtime, transport=httpx.MockTransport(fake_epicstaff_api))
    client = TestClient(build_app(app, runtime, epicstaff=epicstaff))

    call = HookSigner(signer).call(
        "upgrade", org={"id": 3, "name": "Acme"}, job_id=51, previous_version="0.6.0"
    )
    response = client.post(call.path, headers=call.headers, content=call.body)

    assert response.json() == {"status": "done"}
```

Check that it brings what an earlier version made to this version, that it creates what is
missing, that it does nothing for an organization already at this version, that it handles a
`null` `previous_version`, and that a second call changes nothing. The Weather sample's tests
(`src/plugin_sdk/tests/test_weather_sample_backend.py` in the EpicStaff repository) do all of
these against an in-memory fake of the API.

To try a whole upgrade on a stack, see part 5 of
[Build your first plugin](../tutorial/build-your-first-plugin.md#part-5-ship-a-new-version).

## 9. Watch it run

On your plugin's Organizations tab, each organization shows "Upgrading…" with the attempt and
its next try while its hook is pending, then "Active" with the new version, or "Upgrade failed"
with the hook's error and a "Retry" button. The Activity tab records each upgrade hook that
succeeded, failed or was retried, with the version it brought the organization from.
