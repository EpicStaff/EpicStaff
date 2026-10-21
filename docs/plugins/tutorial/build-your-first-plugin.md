# Build your first plugin, part 1: Weather

This tutorial builds the Weather sample plugin, `plugin-samples/weather/` in the EpicStaff
repository, and installs it on a local EpicStaff. By the end:

- a SuperAdmin grants Weather to an organization, and Weather's **install hook** creates a
  "Weather forecast" flow with a daily schedule, and a readme in the organization's storage;
- a member opens Weather, asks for the forecast for Paris, and Weather **runs that flow on their
  behalf** and shows the result;
- an Org Admin enters an LLM key on Weather's settings page, and Weather stores it as an
  EpicStaff Secret with an LLM config that uses it, again on their behalf;
- the organization's Plugin activity shows everything Weather did, and for whom.

Read the sample's files alongside: the tutorial explains them in the order they matter.

## Before you start

- A local EpicStaff with the plugin platform on: [Local development](../how-to/local-development.md)
  and [Enable the plugin platform](../operator/enable-plugins.md).
- Python 3.13 and [uv](https://docs.astral.sh/uv/) for the backend, Node.js for the page.
- A SuperAdmin account, and an organization with an Org Admin and a Member.

## 1. The files

| Path | What it is |
|---|---|
| `plugin-samples/weather/manifest.json` | What the plugin is, what it may do in EpicStaff, who may use it |
| `plugin-samples/weather/icon.svg` | The icon in EpicStaff's left bar |
| `plugin-samples/weather/backend/requirements.in` | The backend's dependencies; `requirements.lock` pins them with hashes |
| `plugin-samples/weather/backend/src/weather_plugin/app.py` | The FastAPI app: the routes the page calls |
| `plugin-samples/weather/backend/src/weather_plugin/install_hook.py` | The install hook |
| `plugin-samples/weather/backend/src/weather_plugin/forecast_flow.py` | The forecast flow, and finding or creating it |
| `plugin-samples/weather/backend/src/weather_plugin/forecast_runs.py` | Which person started which run (in memory: demo only) |
| `plugin-samples/weather/backend/src/weather_plugin/org_settings.py` | The organization's LLM key and config |
| `plugin-samples/weather/spa/src/main.ts` | The page: frame, login, navigation |
| `plugin-samples/weather/spa/src/forecast.ts` | The Forecast page |
| `plugin-samples/weather/spa/src/org-settings.ts` | The Organization settings page |

## 2. The manifest

```json
{
    "manifest_version": 1,
    "id": "weather",
    "version": "0.4.0",
    "name": "Weather",
    "description": "Forecasts for the places your organization cares about.",
    "publisher": { "name": "EpicStaff" },
    "icon": "icon.svg",
    "platform": { "frame_protocol": 1, "gateway_context": 1, "hook_api": 1 },
    "spa": { "entry": "index.html" },
    "backend": { "python": "3.13", "entrypoint": "weather_plugin.app:app" },
    "access": [
        { "resource_type": "flows", "actions": ["read", "create", "update", "use"], "reason": "Creates the Weather forecast flow and runs it for you." },
        { "resource_type": "files", "actions": ["read", "create"], "reason": "Stores the Weather readme in your organization's storage." },
        { "resource_type": "secrets", "actions": ["read", "create", "use"], "reason": "Stores the LLM key an admin enters on the Weather settings page." },
        { "resource_type": "llm_configs", "actions": ["read", "create"], "reason": "Creates the LLM config for Weather summaries." }
    ],
    "user_permissions": [
        {
            "action": "read",
            "description": "Open Weather and see forecasts.",
            "defaults": { "org_admin": true, "member": true, "viewer": false }
        },
        {
            "action": "delete",
            "description": "Change the organization's Weather settings, such as its LLM key.",
            "defaults": { "org_admin": true, "member": false, "viewer": false }
        }
    ],
    "public_paths": [
        { "path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0 },
        { "path": "/api/demo-provider", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 30, "max_body_kb": 0 }
    ],
    "settings": [
        {
            "key": "units",
            "type": "enum",
            "label": "Units",
            "description": "Units every forecast is shown in.",
            "required": true,
            "default": "metric",
            "values": ["metric", "imperial"]
        },
        {
            "key": "forecast_api_token",
            "type": "secret",
            "label": "Forecast API token",
            "description": "Token for a forecast service that needs one; the sample works without it.",
            "required": false
        }
    ],
    "limits": { "memory_mb": 256 },
    "hooks": { "install": true }
}
```

The parts this tutorial uses:

- **`backend`**: a Python 3.13 backend whose ASGI app is `weather_plugin.app:app`.
- **`access`**: what Weather's backend may do in EpicStaff, in the terms of EpicStaff's
  permission catalog, each with the reason the SuperAdmin reads when approving the package.
  Running a flow takes `flows: use`, and so does creating its schedule trigger; storing a Secret
  takes `secrets: create`, and an LLM config that uses it `secrets: use` as well. EpicStaff
  refuses anything else Weather tries, and records everything it creates as Weather's.
- **`user_permissions`**: what people may do in Weather. `read` (View) opens it: Org Admins and
  Members get it, Viewers do not. `delete` is Weather's own "change the organization's settings";
  only Org Admins get it. Custom roles get them in the Roles matrix
  ([Give people permissions](../how-to/user-permissions.md)).
- **`hooks`**: Weather has an install hook.
- **`public_paths`**: `/api/ping` and the demo OAuth provider answer without a login.

[Manifest](../reference/manifest.md) describes every field.

## 3. The install hook

When a SuperAdmin grants Weather to an organization, the grant starts as "Installing…", and the
plugin node calls Weather's install hook. `install_hook.py` registers it with the SDK:

```python
@hook_registry.on_install
async def install(request: HookRequest, epicstaff: OrgClient) -> None:
    await ensure_forecast_flow(epicstaff)
    await ensure_readme(epicstaff)
```

`epicstaff` calls EpicStaff's API as Weather's service account in that organization, alone. The
SDK checked the call's signature before running the handler, so only EpicStaff can start it.

`ensure_forecast_flow` (in `forecast_flow.py`) looks the flow up by a tag in its description
and creates what is missing: the flow, then its nodes in one bulk save. It never takes a flow by
its name alone: if someone in the organization already has a flow named "Weather forecast",
Weather leaves it alone and names its own "Weather forecast (Weather plugin)" (flow names are
unique in an organization). The flow is start, a Python node
"Fetch forecast" that reads `variables.city` (default "Berlin"), asks Open-Meteo for seven days
and writes `variables.forecast`, and end. A schedule trigger "Every day at 06:00 UTC" is created
inactive: an admin turns it on in the flow editor if they want it. `ensure_readme` uploads
`weather/README.md` unless it is there.

Both look up before they create, because a hook can run again for the same organization: a
SuperAdmin retries a failed one. If EpicStaff refuses a call, the handler raises, and the grant
shows "Install failed" with EpicStaff's message and a "Retry install" button.

More in [Write an install hook](../how-to/install-hook.md) and the [Hook API](../reference/hook-api.md).

## 4. The forecast, on behalf of a person

The Forecast page calls three routes of `app.py`:

| Route | Answer |
|---|---|
| `GET /api/forecast/status` | `{"flow": {"id", "name"}}`, or `{"flow": null}` before the install hook ran |
| `POST /api/forecast` with `{"city": "Paris"}` | `202 {"session_id": 81}`; `409 {"code":"not_installed"}` without the flow |
| `GET /api/forecast/{session_id}` | `{"status": "pending" \| "running" \| "finished" \| "failed", "forecast": {...} \| null}` |

Every request reaches the backend with a signed [gateway context](../reference/gateway-context.md)
naming the person and their organization. `POST /api/forecast` runs the flow **on behalf of**
that person:

```python
person_client = epicstaff.client_for_context(context)
flow = await find_forecast_flow(person_client)
session_id = await person_client.run_flow(flow["id"], {"city": body.city})
```

EpicStaff checks that the person may use Weather, runs the flow with Weather's declared access,
and records the person on the run: its principal names the plugin and the person, and the
organization's Plugin activity shows "Weather (plugin) on behalf of" them. The result route
reads the run through `GET /api/sessions/{id}/`, whose `status_data.variables` holds the run's
final variables once it ended (`OrgClient.session` does this), and answers only the person who
started the run, from the map in `forecast_runs.py`. That map lives in memory, which is fine for
one sample process; a real plugin keeps it in its database.

## 5. Settings for admins, and the person's own rights

The Organization settings page is for people with Weather's `delete` permission. The backend
checks it from the context, and answers `403 {"code":"forbidden"}` without it:

| Route | Answer |
|---|---|
| `GET /api/org-settings` | `{"llm_config": {"id", "name"} \| null}` |
| `GET /api/llm-models` | `[{"id", "name"}, ...]`, EpicStaff's model list |
| `PUT /api/org-settings/llm` with `{"llm_model_id", "api_key"}` | Creates the Secret "Weather · LLM key" and the LLM config "Weather summaries"; `409 {"code":"already_configured"}` the second time; `409 {"code":"secret_exists", "message"}` (below) |

EpicStaff checks only Weather's declared access when Weather acts for someone, never that
person's own rights. Creating a Secret and an LLM config is something an Org Admin may do in
EpicStaff, so before it does that for someone, Weather asks EpicStaff who they are and checks:

```python
person = await person_client.person(context.user.id)
if person is None or not all(
    person.has_epicstaff_permission(resource_type, action)
    for resource_type, action in LLM_SETUP_RIGHTS
):
    raise ApiError(403, "forbidden")
```

Weather cannot read, change or delete a Secret, so an attempt that fails between creating the
Secret and the LLM config leaves the Secret behind. The next attempt uses it when the admin
enters the same key, which Weather tells from the last four characters EpicStaff shows of every
Secret. With another key it answers `409 secret_exists`, with a message asking the admin to
delete "Weather · LLM key" in Settings → Secrets first.

[Call EpicStaff from your backend](../how-to/call-epicstaff-from-the-backend.md) covers the
client, on behalf of, and the people endpoint.

## 6. The page

The page is a single-page app in the frame, using the [JS SDK](../reference/js-sdk.md) to log the
person in and call the backend with their token. `forecast.ts` posts the city, then asks for the
run every 2 seconds for up to 2 minutes. `org-settings.ts` shows itself in the navigation only
when `GET /api/whoami` lists `delete` among the person's permissions, and otherwise says "You
need the Delete permission on Weather". [Frontend in the frame](../how-to/frontend-in-the-frame.md)
explains the frame and the login.

Build it:

```
npm --prefix plugin-samples/weather/spa ci
npm --prefix plugin-samples/weather/spa run build
```

## 7. Test the backend

The SDK's test helpers stand in for EpicStaff: `ContextSigner` signs gateway contexts,
`HookSigner` signs hook calls, `write_runtime_file` writes a runtime file with a service-account
key, and an `httpx.MockTransport` answers for EpicStaff's API. The sample's tests, in the
EpicStaff repository, run the install hook twice and check that it created one flow and one
readme, and check every route above:

```
make plugin_sdk-tests ARGS="tests/test_weather_sample_backend.py"
```

## 8. Pack, approve, grant

From the root of the EpicStaff repository (the SDK is not on an index yet, so the package gets
it from a wheel you build):

```
uv build --project src/plugin_sdk --wheel -o dist
uv run --project src/plugin_sdk epicstaff-plugin pack plugin-samples/weather --spa-dir plugin-samples/weather/spa/dist --download-wheels --local-wheel dist/epicstaff_plugin-0.1.0-py3-none-any.whl --out weather-0.4.0.esplugin
uv run --project src/plugin_sdk epicstaff-plugin validate weather-0.4.0.esplugin
```

[Sign and package a plugin](../how-to/sign-and-package.md) adds a signature. Then, as the
SuperAdmin, in EpicStaff's Plugins page: upload `weather-0.4.0.esplugin`, read the review (the
declared access, with its reasons), approve it, and grant it to your organization. The grant
shows "Installing…", then "Active", with the service account and "Owned resources: 2".

## 9. Use it

- As the Member, open Weather, go to Forecast, enter "Paris" and ask for the forecast.
- As the Org Admin, open the flow "Weather forecast" in EpicStaff, and `weather/README.md` in
  Storage. Open Weather's Organization settings, pick a model, enter a key; the Secret and the
  LLM config appear in EpicStaff's settings.
- As the Org Admin, open Settings, then Plugin activity: Weather is listed with its declared
  access, and every change it made is there, with the person it acted for.
