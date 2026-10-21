# Build your first plugin: Weather

This tutorial builds the Weather sample plugin, `plugin-samples/weather/` in the EpicStaff
repository, and installs it on a local EpicStaff. It comes in three parts:

1. [A backend that works in EpicStaff](#part-1-a-backend-that-works-in-epicstaff). A
   SuperAdmin grants Weather to an organization, and Weather's **install hook** creates a
   "Weather forecast" flow with a daily schedule, and a readme in the organization's storage. A
   member asks for the forecast for Paris, and Weather **runs that flow on their behalf**. An Org
   Admin enters an LLM key, and Weather stores it as an EpicStaff Secret with an LLM config that
   uses it. The organization's Plugin activity shows everything Weather did, and for whom.
2. [Saved places in the plugin's database](#part-2-saved-places-in-the-plugins-database).
   Weather gets a **database of its own**. Each organization keeps its own list of places in it,
   and no organization sees another's.
3. [Search through an outbound host](#part-3-search-through-an-outbound-host). Weather finds
   places by name at Open-Meteo, through the **egress proxy**, which lets the backend reach the
   one host its manifest declares and nothing else.

Read the sample's files alongside: each part explains them in the order they matter.

## Before you start

- A local EpicStaff with the plugin platform on: [Local development](../how-to/local-development.md)
  and [Enable the plugin platform](../operator/enable-plugins.md), including the plugin database
  server and the egress proxy, and a Docker host that reaches the internet (for part 3).
- Python 3.13 and [uv](https://docs.astral.sh/uv/) for the backend, Node.js for the page.
- A SuperAdmin account, and an organization with an Org Admin and a Member.

## The files

| Path | What it is |
|---|---|
| `plugin-samples/weather/manifest.json` | What the plugin is, what it may do in EpicStaff, who may use it, its database and its outbound host |
| `plugin-samples/weather/icon.svg` | The icon in EpicStaff's left bar |
| `plugin-samples/weather/backend/requirements.in` | The backend's dependencies; `requirements.lock` pins them with hashes |
| `plugin-samples/weather/backend/src/weather_plugin/app.py` | The FastAPI app: the routes the page calls, and the lifespan that opens the database |
| `plugin-samples/weather/backend/src/weather_plugin/install_hook.py` | The install hook |
| `plugin-samples/weather/backend/src/weather_plugin/forecast_flow.py` | The forecast flow, and finding or creating it |
| `plugin-samples/weather/backend/src/weather_plugin/forecast_runs.py` | Which person started which run |
| `plugin-samples/weather/backend/src/weather_plugin/org_settings.py` | The organization's LLM key and config |
| `plugin-samples/weather/backend/src/weather_plugin/popup_relay.py` | The popup relay of [External callbacks](../how-to/external-callbacks.md) |
| `plugin-samples/weather/database/migrations/001_weather.sql` | Weather's tables, with row-level security per organization (part 2) |
| `plugin-samples/weather/backend/src/weather_plugin/database.py` | The connection pool, and a transaction per organization (part 2) |
| `plugin-samples/weather/backend/src/weather_plugin/places.py` | The saved places (part 2) |
| `plugin-samples/weather/backend/src/weather_plugin/place_search.py` | Finding places by name through the egress proxy (part 3) |
| `plugin-samples/weather/spa/src/main.ts` | The page: frame, login, navigation |
| `plugin-samples/weather/spa/src/forecast.ts` | The Forecast page; `/forecast?city=<name>` fills the city field, and the parameter is then removed from the address |
| `plugin-samples/weather/spa/src/places.ts` | The Places page: saved places, search and Add (parts 2–3) |
| `plugin-samples/weather/spa/src/org-settings.ts` | The Organization settings page |

## The manifest

```json
{
    "manifest_version": 1,
    "id": "weather",
    "version": "0.5.0",
    "name": "Weather",
    "description": "Forecasts for the places your organization cares about.",
    "publisher": { "name": "EpicStaff" },
    "icon": "icon.svg",
    "platform": { "frame_protocol": 1, "gateway_context": 1, "hook_api": 1 },
    "spa": { "entry": "index.html" },
    "backend": { "python": "3.13", "entrypoint": "weather_plugin.app:app" },
    "database": {},
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
            "action": "update",
            "description": "Add and remove saved places.",
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
    "outbound_hosts": [
        { "host": "geocoding-api.open-meteo.com", "reason": "Looks up places by name when someone adds a saved place." }
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
    "limits": { "memory_mb": 256, "db_connections": 3, "statement_timeout_seconds": 10 },
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
  Members get it, Viewers do not. `update` (Edit) is Weather's own "add and remove saved places"
  (part 2): Org Admins and Members get it. `delete` is Weather's own "change the organization's
  settings"; only Org Admins get it. Custom roles get them in the Roles matrix
  ([Give people permissions](../how-to/user-permissions.md)).
- **`hooks`**: Weather has an install hook.
- **`public_paths`**: `/api/ping` and the demo OAuth provider answer without a login.
- **`database`** and the `db_connections` and `statement_timeout_seconds` limits: part 2.
- **`outbound_hosts`**: part 3.

[Manifest](../reference/manifest.md) describes every field.

## Part 1: a backend that works in EpicStaff

### 1. The install hook

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

### 2. The forecast, on behalf of a person

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
started the run. Which person started which run is kept in Weather's database (part 2), so a run
started before a restart is still found after it.

The flow's Python node runs inside EpicStaff, in its sandbox, so its calls to Open-Meteo are
EpicStaff's, not the plugin's: they need no outbound host (part 3).

### 3. Settings for admins, and the person's own rights

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

### 4. The page

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

### 5. Test the backend

The SDK's test helpers stand in for EpicStaff: `ContextSigner` signs gateway contexts,
`HookSigner` signs hook calls, `write_runtime_file` writes a runtime file with a service-account
key, and an `httpx.MockTransport` answers for EpicStaff's API. The sample's tests, in the
EpicStaff repository, run the install hook twice and check that it created one flow and one
readme, and check every route above:

```
make plugin_sdk-tests ARGS="tests/test_weather_sample_backend.py"
```

### 6. Pack, approve, grant

From the root of the EpicStaff repository (the SDK is not on an index yet, so the package gets
it from a wheel you build):

```
uv build --project src/plugin_sdk --wheel -o dist
uv run --project src/plugin_sdk epicstaff-plugin pack plugin-samples/weather --spa-dir plugin-samples/weather/spa/dist --download-wheels --local-wheel dist/epicstaff_plugin-0.1.0-py3-none-any.whl --out weather-0.5.0.esplugin
uv run --project src/plugin_sdk epicstaff-plugin validate weather-0.5.0.esplugin
```

[Sign and package a plugin](../how-to/sign-and-package.md) adds a signature. Then, as the
SuperAdmin, in EpicStaff's Plugins page: upload `weather-0.5.0.esplugin`, read the review (the
declared access with its reasons, the database and the outbound host), approve it, and grant it
to your organization. The grant shows "Installing…", then "Active", with the service account and
"Owned resources: 2".

### 7. Use it

- As the Member, open Weather, go to Forecast, enter "Paris" and ask for the forecast.
- As the Org Admin, open the flow "Weather forecast" in EpicStaff, and `weather/README.md` in
  Storage. Open Weather's Organization settings, pick a model, enter a key; the Secret and the
  LLM config appear in EpicStaff's settings.
- As the Org Admin, open Settings, then Plugin activity: Weather is listed with its declared
  access, and every change it made is there, with the person it acted for.

## Part 2: saved places in the plugin's database

Each organization keeps a list of places on Weather's Places page. One database holds every
organization's places, and row-level security keeps each organization to its own.

### 1. Ask for a database

The manifest asks for a database with `"database": {}`, which needs a `backend`. Its `limits`
ask for 3 connections and a statement timeout of 10 seconds; without them the deployment's
defaults apply ([Limits](../reference/limits.md)). `requirements.in` adds a driver and a
connection pool, `psycopg[binary,pool]`: the SDK depends on no database driver.

When the SuperAdmin approves the package, EpicStaff records a database for Weather. Before the
backend first starts, the plugin node creates it on the deployment's plugin database server:
the database `plugin_weather`, and three roles, `weather_owner`, `weather_app` and
`weather_job`. It runs the migrations under `database/migrations/` as `weather_owner`, then
starts the backend with two more variables in its environment: `DATABASE_URL`, which logs in
as `weather_app`, and `EPICSTAFF_PLUGIN_DB_CONNECTIONS`, that role's connection limit.
[Plugin database](../reference/database.md) describes the roles and what each may do.

### 2. The migration

`plugin-samples/weather/database/migrations/001_weather.sql` creates the schema `weather` with
three tables: `saved_places`, and the two stores part 1 kept, `forecast_runs` and
`popup_results`. Every row carries its organization's id, and every table has a policy that
shows a session only the rows of the organization the setting `app.org_id` names:

```sql
ALTER TABLE weather.saved_places ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather.saved_places FORCE ROW LEVEL SECURITY;
CREATE POLICY org_rows ON weather.saved_places
    USING (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint)
    WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::bigint);
```

A session that has not set `app.org_id` sees no rows and can write none. The file ends by
granting the backend's role what it needs, and nothing more:

```sql
GRANT USAGE ON SCHEMA weather TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE
    ON weather.saved_places, weather.forecast_runs, weather.popup_results
    TO ${app_role};
GRANT USAGE ON SEQUENCE weather.saved_places_id_seq TO ${app_role};
```

`${app_role}` is a placeholder the node replaces with the quoted name of the app role. The node
runs each file once, in one transaction, so the file has no `BEGIN` or `COMMIT` of its own.
[Write database migrations](../how-to/database-migrations.md) covers the rules.

### 3. One transaction per organization

`database.py` holds the pool. Every query of the backend runs in
`WeatherDatabase.transaction(org_id)`, which takes a connection and opens the SDK's
`org_transaction` on it:

```python
async with self._pool.connection() as connection, org_transaction(connection, org_id):
    yield connection
```

`org_transaction` sets `app.org_id` for that transaction only, so a pooled connection never
carries one organization's id into the next request. The queries in `places.py` then need no
`WHERE org_id`: removing a place is `DELETE FROM weather.saved_places WHERE id = %s`, and
another organization's id finds nothing to delete.

### 4. Open the pool in the lifespan

`app.py` opens the database in the app's lifespan, before the first request:

```python
database = await WeatherDatabase.open()
```

`WeatherDatabase.open` sizes the pool to the role's limit, `AsyncConnectionPool(database_url(),
min_size=1, max_size=connection_limit())`, and waits until one connection works. A backend whose
database cannot be reached does not start, and the node restarts it.

### 5. The Places routes

| Route | Answer |
|---|---|
| `GET /api/places` | `{"places": [{"id", "name", "admin1", "country", "latitude", "longitude", "created_at"}]}`, the organization's places by name |
| `POST /api/places` with one search result (part 3) | `201` with the saved place; `409 {"code":"already_saved"}` when the organization has a place of that name, region (`admin1`) and country; `403 {"code":"forbidden"}` without Edit |
| `DELETE /api/places/{place_id}` | `204`; `404 {"code":"not_found"}` for an unknown id or another organization's place |

Adding and removing need Weather's `update` (Edit), which the backend checks from the context.
The forecast runs of part 1 and the popup relay's results are in the same database, with the
same policy.

### 6. What administrators see

- The SuperAdmin's review shows a **Database** section: Weather gets its own database, and one
  migration runs before the backend first starts.
- About a minute after approval, the plugin's Runtime tab shows **Database: Ready**, with the
  database, its roles, "Migrations: 1 of 1", the connection limit, the statement timeout and the
  size. The Activity tab shows "Database ready", by the platform.
- Org Admins see "Keeps its data in its own database" on Weather's card in Settings → Plugin
  activity.

### 7. Test it

The backend tests of part 1 also run the Places routes, with in-memory stand-ins for the
stores. The stores themselves run against a real PostgreSQL in `src/plugin_sdk/tests/test_weather_sample_database.py`,
which sets the database up as the node does and applies the sample's migration. Point
`ES_PLUGINS_TEST_PG_HOST`, `ES_PLUGINS_TEST_PG_PORT` and `ES_PLUGINS_TEST_PG_ADMIN_PASSWORD` at a
plugin database server, then:

```
make plugin_sdk-tests ARGS="-m postgres tests/test_weather_sample_database.py"
```

### 8. Use it

- As the Member, open Weather, go to Places, search for "Lisbon" (part 3) and add "Lisbon,
  Portugal". The page leaves out the region when it repeats the place's name. The Org Admin sees
  the place too.
- "Forecast" next to a place opens the Forecast page with its name in the city field.
- Someone whose role gives Weather View only sees the list, without the search, Add or Remove.
- In another organization, the list is empty, and the places added there are not in yours.
- Restart the plugin from its Runtime tab: the places are still there.

## Part 3: search through an outbound host

A backend reaches the internet only through the deployment's egress proxy, and only the hosts
its manifest lists. Weather lists one.

### 1. Declare the host

```json
"outbound_hosts": [
    { "host": "geocoding-api.open-meteo.com", "reason": "Looks up places by name when someone adds a saved place." }
]
```

The SuperAdmin's review shows the host with its reason, and that it is reached over HTTPS on
port 443 only, through the egress proxy. Org Admins see it on Weather's card in Settings →
Plugin activity, and the Runtime tab lists it under **Outbound access**.
[Call the internet from your backend](../how-to/outbound-hosts.md) covers exact names, `*.`
wildcards and the limits.

### 2. The search route

| Route | Answer |
|---|---|
| `GET /api/places/search` with `?q=Lisbon` | `{"results": [{"name", "country", "admin1", "latitude", "longitude"}]}`, up to five; `400 {"code":"invalid_request"}` when `q` is blank or longer than 100 characters; `502 {"code":"lookup_failed"}` when the proxy refuses or Open-Meteo fails |

`place_search.py` asks `https://geocoding-api.open-meteo.com/v1/search` with `name`, `count=5`
and `format=json`, with an httpx client that reads the proxy from the environment:

```python
self._http = httpx.AsyncClient(
    transport=transport,
    trust_env=True,
    follow_redirects=False,
    timeout=SEARCH_TIMEOUT_SECONDS,
)
```

The node puts the proxy's address, with Weather's own credentials, in `HTTPS_PROXY`, and
EpicStaff's API in `NO_PROXY`. `trust_env=True` is httpx's default, so the sample only spells it
out. The SDK's EpicStaff client never uses the proxy. A result is one of the
`POST /api/places` bodies of part 2; results without a country are left out.

### 3. When the proxy refuses

When the backend asks the proxy for a host the manifest does not list, or for another port than
443, the proxy refuses the tunnel with `403`, which httpx raises as `httpx.ProxyError`. The
search route then answers `502 {"code":"lookup_failed"}`, and the backend's log says "Place
search failed: ProxyError".
[Call the internet from your backend](../how-to/outbound-hosts.md#when-the-proxy-refuses) lists
every refusal.

### 4. Test it

The tests answer for Open-Meteo with an `httpx.MockTransport`, and check the address and
parameters the search asks for, and that a failed lookup is `lookup_failed`. One test runs the
real clients against a local proxy that refuses like the egress proxy: the search tunnels to
`geocoding-api.open-meteo.com:443` with Weather's credentials, and the EpicStaff client goes
direct, never through the proxy.

### 5. Use it

- As the Member, open Weather, go to Places and search for "Lisbon": the matches come from
  Open-Meteo, through the egress proxy.
- The plugin's Runtime tab lists `geocoding-api.open-meteo.com` under **Outbound access**.
