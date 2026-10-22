# Delete your data when an organization leaves

When an organization no longer has your plugin, EpicStaff deletes everything your plugin created
in it, and asks your backend to delete what it keeps for the organization itself: rows in your
database, files on the node, anything in other systems. That request is the **organization
removed hook**. This guide builds one with the Python SDK, after the Weather sample. The
[Hook API](../reference/hook-api.md#what-happens-when-an-organizations-data-is-deleted) is the
reference.

## 1. When it runs

EpicStaff calls the hook for an organization:

- when the organization's data is deleted: its grace period ended after it was suspended, or a
  SuperAdmin chose **Delete data…** for it;
- when the organization is deleted;
- for every organization, when your plugin is deleted.

By then the organization's service account and keys are revoked. Nobody in the organization can
open your plugin, and your backend has no key to call EpicStaff with for it. The organization
itself may already be gone. The hook's `request.org.name` is the name the organization had when
its deletion started.

If your plugin is uninstalled, its process is stopped. EpicStaff starts it again only to run the
hook, and stops it once no hook is waiting. Your backend then starts as usual, with its
database, so keep its startup independent of any one organization.

## 2. Ask for it in the manifest

```json
"hooks": { "install": true, "org_removed": true }
```

The hook needs a `backend`. It may take up to 15 minutes, the platform maximum; a shorter limit
goes in `"timeouts_seconds": { "org_removed": 300 }`. The SuperAdmin's review lists "Hooks:
install, organization removed".

Without `"org_removed": true`, EpicStaff deletes only what your plugin created in EpicStaff. What
your backend keeps for the organization then stays until your plugin is deleted, and its
database with it.

## 3. Register a handler

Register one async function that takes the request alone:

```python
from epicstaff_plugin.contracts.hook_api import HookRequest
from epicstaff_plugin.hooks import hook_registry


@hook_registry.on_org_removed
async def org_removed(request: HookRequest) -> None:
    deleted = await app.state.organization_data.delete(request.org.id)
    logger.info(
        "Deleted %s rows of organization %s (job %s)", deleted, request.org.id, request.job_id
    )
```

Unlike an install hook, it gets no `OrgClient`: there is no key to make one with. A handler that
takes a second argument is refused when it is registered, with a `TypeError`, so the mistake
shows when your backend starts rather than on the first deletion.

Register it at import time of your entrypoint module, like the install hook. The Weather sample
defines it in `plugin-samples/weather/backend/src/weather_plugin/app.py`, next to the lifespan
that opens the database it deletes from. The deleting itself is in
`plugin-samples/weather/backend/src/weather_plugin/organization_data.py`:

```python
DELETE_ORGANIZATION_ROWS = (
    "DELETE FROM weather.place_conditions WHERE org_id = %s",
    "DELETE FROM weather.saved_places WHERE org_id = %s",
    "DELETE FROM weather.forecast_runs WHERE org_id = %s",
    "DELETE FROM weather.popup_results WHERE org_id = %s",
)


class OrganizationData:
    async def delete(self, org_id: int) -> int:
        deleted = 0
        async with self._database.transaction(org_id) as connection:
            for statement in DELETE_ORGANIZATION_ROWS:
                cursor = await connection.execute(statement, (org_id,))
                deleted += cursor.rowcount
        return deleted
```

## 4. Delete only your own data

- **Your database.** Delete the organization's rows in one `org_transaction` for it, so
  row-level security limits every statement to that organization, and say `WHERE org_id = %s`
  as well. Then a mistake in either still deletes nothing of another organization's. List every
  table with organization rows: the Weather sample's tests compare its statements with the
  tables its migrations create, so a new table cannot be forgotten. A table whose rows go with
  another's, like Weather's `place_conditions` with its places, comes first: the cascade would
  delete its rows anyway, but they would not be counted.
- **Memory.** Clear anything the process keeps for the organization: caches, sessions,
  connections to other systems. The Weather sample keeps nothing per organization in memory.
- **Other systems.** Revoke the organization's tokens and delete what you stored for it at
  third parties.
- **Not EpicStaff.** EpicStaff deletes the flows, files, Secrets, configurations and everything
  else your plugin created in the organization, including what it made on behalf of people. Do
  not try to: you have no key, and every call would be refused.

A big delete can pass your database role's statement timeout (`limits.statement_timeout_seconds`).
Then every attempt fails the same way. Delete in batches, each in a transaction of its own, if
an organization's rows can run into the millions.

## 5. Make it safe to run again

The hook can run more than once for one organization. A failed attempt is tried again, a
SuperAdmin can retry it, and a new job can come for an organization whose data an earlier one
already deleted. Write it so that running it again simply finds less to delete. A `DELETE`
that finds nothing succeeds, so the Weather hook needs no bookkeeping.

## 6. When it fails

Raise to fail the hook: the first line of the exception is what the SuperAdmin reads. EpicStaff
then tries again by itself: 1 minute after the first attempt, 5 minutes after the second, 30
minutes after the third, then every hour, for 7 days from the first attempt. A backend that does
not answer, times out, or has no handler (`501`) counts as a failed attempt too.

After 7 days the hook stays failed and the plugin shows "Needs attention". The SuperAdmin can:

- **Retry** it, which starts 7 more days of attempts;
- **Skip** it, at any time, also while it waits for its next attempt. Your data for that
  organization then stays where your plugin keeps it, until your plugin itself is deleted.

While the hook has neither succeeded nor been skipped, the organization's grant stays, as
"Deleting data…". When your plugin itself is deleted, a failed hook holds nothing up: its
database and files are deleted with it.

## 7. Test it

`epicstaff_plugin.testing.HookSigner` signs hook calls as EpicStaff does. Call the hook for an
organization your runtime file has no service account for, as EpicStaff will. Here the app's
lifespan opens a test database that your migrations set up (`test_database_url`, a fixture of
your own):

```python
from epicstaff_plugin.runtime import RuntimeConfig
from epicstaff_plugin.serve import build_app
from epicstaff_plugin.testing import ContextSigner, HookSigner, write_runtime_file
from fastapi.testclient import TestClient
from weather_plugin.app import app


def test_the_org_removed_hook_succeeds(tmp_path, monkeypatch, test_database_url):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_DB_CONNECTIONS", "3")
    signer = ContextSigner(plugin_identifier="weather", plugin_version="0.7.0")
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)

    # Entering the client runs the lifespan, which opens the database.
    with TestClient(build_app(app, RuntimeConfig.load(runtime_file))) as client:
        call = HookSigner(signer).call("org_removed", org={"id": 9, "name": "Cobalt"}, job_id=61)
        response = client.post(call.path, headers=call.headers, content=call.body)

    assert response.json() == {"status": "done"}
```

Check that it deletes the organization's rows and leaves another organization's, that a second
call succeeds, and that it never calls EpicStaff. The Weather sample's tests
(`src/plugin_sdk/tests/test_weather_sample_backend.py` and, against a real PostgreSQL,
`src/plugin_sdk/tests/test_weather_sample_database.py`) do all of these.

## 8. Watch it run

On your plugin's Organizations tab, an organization whose data is being deleted shows
"Deleting data…" with the hook's state, its next attempt and its last error, and "Retry" or
"Skip" when they apply. Deleted organizations are listed apart, by the name they had. The
Activity tab records each hook that succeeded, failed for good, was retried or was skipped.
