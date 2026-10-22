# Weather sample plugin

A complete EpicStaff plugin: a single-page app in EpicStaff's frame (`spa/`, using the JS SDK
in `plugin-sdk/`), a FastAPI backend (`backend/`, using the Python SDK in `src/plugin_sdk/`),
and a database of its own (`database/migrations/`).
[Build your first plugin](../../docs/plugins/tutorial/build-your-first-plugin.md) walks through
it.

## Build, pack and install it

Run these from the root of the EpicStaff repository, for an EpicStaff with the plugin platform on
([Local development](../../docs/plugins/how-to/local-development.md#run-epicstaff-for-plugin-development)).
You need Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node.js 24.15 or later.

```bash
npm --prefix plugin-sdk ci && npm --prefix plugin-sdk run build
npm --prefix plugin-samples/weather/spa ci && npm --prefix plugin-samples/weather/spa run build
uv build --project src/plugin_sdk --wheel -o dist
uv run --frozen --project src/plugin_sdk epicstaff-plugin pack plugin-samples/weather --spa-dir plugin-samples/weather/spa/dist --download-wheels --local-wheel dist/epicstaff_plugin-0.1.0-py3-none-any.whl --out weather-0.7.0.esplugin
uv run --frozen --project src/plugin_sdk epicstaff-plugin validate weather-0.7.0.esplugin
```

Add `--key <your secret key>` to `pack` to sign it
([Sign and package a plugin](../../docs/plugins/how-to/sign-and-package.md)). As a SuperAdmin,
upload `weather-0.7.0.esplugin` under **Workspace → Plugins**, approve it and grant it to an
organization.

## Develop it

On an EpicStaff in plugin development mode, run the backend and the page from this directory,
and point the installed Weather at them on its **Development** tab
([Local development](../../docs/plugins/how-to/local-development.md#develop-the-backend-on-your-machine)):

```bash
uv venv --python 3.13 plugin-samples/weather/.venv
uv pip install --python plugin-samples/weather/.venv --require-hashes -r plugin-samples/weather/backend/requirements.lock
uv pip install --python plugin-samples/weather/.venv --no-deps ./src/plugin_sdk
source plugin-samples/weather/.venv/bin/activate
epicstaff-plugin dev plugin-samples/weather --runtime-file ~/weather-dev/weather-development-runtime.json --port 8001 --database-url postgresql://weather_app:choose-a-password@127.0.0.1:5433/weather_development --apply-migrations
```

and, in another terminal, the page's development server on port 5173:

```bash
npm --prefix plugin-samples/weather/spa run dev
```

The runtime file is the one you download from the Development tab; keep it outside this
directory. The database is a local PostgreSQL 16 or later with the two roles
[A database for the development backend](../../docs/plugins/how-to/local-development.md#a-database-for-the-development-backend)
creates. `.gitignore` keeps `.venv/` and development runtime files out of version control.

## What the backend does

- **Install hook** (`backend/src/weather_plugin/install_hook.py`). In every organization Weather
  is granted to, it creates the flow "Weather forecast" with an inactive daily schedule, and
  `weather/README.md` in the organization's storage. Running it again only adds what is missing,
  and gives a flow an earlier version made this version's description and fetch code.
- **Upgrade hook** (`backend/src/weather_plugin/upgrade_hook.py`). When an organization moves to
  a new version of Weather, it runs the install hook's steps again, so the organization's flow
  gets this version's description, "Forecast for a city · Weather 0.7.0", and whatever is missing
  is created. It does nothing for an organization already at 0.7.0 or later
  (`FLOW_VERSION` in `backend/src/weather_plugin/forecast_flow.py`), and treats an organization
  that never finished installing as a fresh install. Running it again changes nothing.
- **Organization removed hook** (`org_removed` in `backend/src/weather_plugin/app.py`, deleting
  through `backend/src/weather_plugin/organization_data.py`). When an organization's Weather data
  is deleted, when the organization is deleted, or when Weather is deleted, it deletes the
  organization's saved places, their temperatures, forecast runs and popup results from
  Weather's database, in one transaction. It never calls EpicStaff, which deletes the flow, the readme, the Secret and the
  LLM config itself. Running it again deletes nothing more.
- **Forecast** (`/api/forecast`). Runs that flow for a city, on behalf of the person asking.
- **Organization settings** (`/api/org-settings`). For people with Weather's Delete permission:
  stores an LLM key as the Secret "Weather · LLM key" and creates the LLM config
  "Weather summaries", on behalf of the admin.
- **Saved places** (`/api/places`). Each organization's list of places, in Weather's database,
  in the order they were saved; adding and removing need Weather's Edit permission.
- **Current temperatures** (`backend/src/weather_plugin/current_conditions.py`). The list gives
  each place its temperature, looked up at Open-Meteo's forecast API (`api.open-meteo.com`)
  through the egress proxy when it is missing or older than 15 minutes, for at most 10 places
  per request. A failed lookup keeps the stored temperature and never fails the list.
- **Place search** (`/api/places/search`). Finds places by name at Open-Meteo's geocoding API,
  through the egress proxy: `geocoding-api.open-meteo.com` is the other outbound host the
  manifest declares.

## Things to know

- **Weather finds its flow by a tag** in the flow's description
  (`[weather-plugin:forecast-flow]`), never by its name alone. A flow a person named
  "Weather forecast" is never adopted, changed or run; Weather then names its own
  "Weather forecast (Weather plugin)", since flow names are unique in an organization. Keep the
  tag in the description: without it Weather no longer finds the flow, and the next install
  creates a new one.
- **The LLM is set up once.** Weather cannot read, change or delete Secrets. If setting it up
  fails after the Secret was created, trying again with the same key finishes the job; with
  another key Weather asks the admin to delete "Weather · LLM key" in Settings → Secrets first.
  To change the key later, change the LLM config in EpicStaff's own settings.
- **Everything Weather keeps is in its database**, in the schema `weather`: the saved places and
  their temperatures, which person started which forecast run (`backend/src/weather_plugin/forecast_runs.py`) and the popup
  relay's results (`backend/src/weather_plugin/popup_relay.py`). Every table has row-level security on `org_id`, and
  every query runs in one organization's transaction (`backend/src/weather_plugin/database.py`), so an organization
  never sees another's rows.
  A restart loses nothing.
- **Version 0.7.0 added a migration**, `database/migrations/003_place_conditions.sql`: each saved
  place's position, numbered for the places already saved, and the table of temperatures. The
  earlier files stay as they are: a new version adds files and never changes one that ran.
- **Old rows are purged hourly** (`backend/src/weather_plugin/retention.py`). A forecast run is kept for 7 days and a popup
  result until it expires, after five minutes. Once an hour the backend deletes older rows of
  every organization, in batches, as the plugin's job role. Its policies, in
  `database/migrations/002_retention.sql`, let it read only the timestamps of expired rows and
  delete only those rows.
- **The demo OAuth provider** (`/api/demo-provider`, a public path) stands in for an external
  service, to show the popup hand-off; see
  [Receive an external provider's callback](../../docs/plugins/how-to/external-callbacks.md).
