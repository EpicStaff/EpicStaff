# Weather sample plugin

A complete EpicStaff plugin: a single-page app in EpicStaff's frame (`spa/`, using the JS SDK
in `plugin-sdk/`) and a FastAPI backend (`backend/`, using the Python SDK in `src/plugin_sdk/`).
[Build your first plugin](../../docs/plugins/tutorial/build-your-first-plugin.md) walks through
it, and shows how to pack it.

## What the backend does

- **Install hook** (`backend/src/weather_plugin/install_hook.py`). In every organization Weather
  is granted to, it creates the flow "Weather forecast" with an inactive daily schedule, and
  `weather/README.md` in the organization's storage. Running it again only adds what is missing.
- **Forecast** (`/api/forecast`). Runs that flow for a city, on behalf of the person asking.
- **Organization settings** (`/api/org-settings`). For people with Weather's Delete permission:
  stores an LLM key as the Secret "Weather · LLM key" and creates the LLM config
  "Weather summaries", on behalf of the admin.

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
- **The in-process stores are for the demo only.** Which person started which forecast run
  (`forecast_runs.py`) and the popup relay's results (`popup_relay.py`) live in the backend
  process's memory: enough for one sample process, but lost on every restart. A real plugin
  keeps them in its database.
- **The demo OAuth provider** (`/api/demo-provider`, a public path) stands in for an external
  service, to show the popup hand-off; see
  [Receive an external provider's callback](../../docs/plugins/how-to/external-callbacks.md).
