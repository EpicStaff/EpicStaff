"""The "Weather forecast" flow: start, a Python node that fetches the forecast, end.

The install hook creates it in every organization Weather is granted to, together with a
daily schedule trigger that is created inactive, so an admin decides whether it runs. The
forecast page runs it for a person with `variables.city` set; the Python node writes the
forecast to `variables.forecast`.

Weather finds its own flow by a tag in the flow's description, never by its name alone, so a
flow a person named "Weather forecast" is never adopted, changed or run. Flow names are unique
in an organization: when a person's flow already has that name, Weather names its own
"Weather forecast (Weather plugin)". Removing the tag from the description makes Weather lose
the flow; the next install creates a new one.

Every step looks up what is already there, so the hook can run again for the same organization
(a retried job) and only adds what an earlier attempt did not finish.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from epicstaff_plugin.client import OrgClient

FLOW_NAME = "Weather forecast"
FLOW_NAME_WHEN_TAKEN = "Weather forecast (Weather plugin)"
FLOW_TAG = "[weather-plugin:forecast-flow]"
FLOW_DESCRIPTION = (
    "Fetches a seven-day forecast from Open-Meteo. Created by the Weather plugin, which finds "
    f"it by this tag: {FLOW_TAG}"
)
FETCH_NODE_NAME = "Fetch forecast"
SCHEDULE_NODE_NAME = "Every day at 06:00 UTC"
DEFAULT_CITY = "Berlin"
# How many flows one lookup reads; more matches than that are not searched further.
FLOW_LOOKUP_LIMIT = 100

# Runs in EpicStaff's sandbox, not in this plugin: standard library only.
FETCH_FORECAST_CODE = """\
import json
import urllib.parse
import urllib.request


def _get(url, query):
    with urllib.request.urlopen(f"{url}?{urllib.parse.urlencode(query)}", timeout=20) as response:
        return json.load(response)


def main(city="Berlin"):
    city = (city or "Berlin").strip() or "Berlin"
    places = _get(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": city, "count": 1, "format": "json"},
    ).get("results") or []
    if not places:
        raise ValueError(f"No place called {city!r}")
    place = places[0]
    daily = _get(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "daily": "temperature_2m_max,temperature_2m_min",
            "timezone": "UTC",
            "forecast_days": 7,
        },
    )["daily"]
    return {
        "city": place["name"],
        "days": [
            {"date": day, "temperature_max": high, "temperature_min": low}
            for day, high, low in zip(
                daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"]
            )
        ],
    }
"""


async def find_forecast_flow(epicstaff: OrgClient) -> dict[str, Any] | None:
    """Return Weather's forecast flow in the organization as `{"id", "name"}`, or None.

    The flow is the one whose description carries Weather's tag; the oldest wins when a copy
    carries it too.
    """
    flows = [
        flow
        for flow in await _search_flows(epicstaff, FLOW_TAG)
        if FLOW_TAG in (flow.get("description") or "")
    ]
    if not flows:
        return None
    oldest = min(flows, key=lambda flow: flow["id"])
    return {"id": oldest["id"], "name": oldest["name"]}


async def ensure_forecast_flow(epicstaff: OrgClient) -> int:
    """Create the flow, its nodes and its schedule where they are missing; return its id.

    Raises:
        EpicStaffApiError: EpicStaff refused a call; the hook fails with its message.
    """
    flow = await find_forecast_flow(epicstaff)
    if flow is None:
        created = await epicstaff.post(
            "graphs/", {"name": await _free_flow_name(epicstaff), "description": FLOW_DESCRIPTION}
        )
        graph_id = created["id"]
    else:
        graph_id = flow["id"]
    graph = await epicstaff.get(f"graphs/{graph_id}/")
    if not any(node["node_name"] == FETCH_NODE_NAME for node in graph["python_node_list"]):
        # One request, one transaction: an attempt that fails here leaves the flow empty,
        # and the next attempt fills it.
        await epicstaff.post(
            f"graphs/{graph_id}/save/",
            flow_contents(graph_id, graph["save_version"], datetime.now(UTC)),
        )
    return graph_id


async def _free_flow_name(epicstaff: OrgClient) -> str:
    # Called only when no flow carries the tag, so a flow of this name is someone else's.
    taken = any(flow["name"] == FLOW_NAME for flow in await _search_flows(epicstaff, FLOW_NAME))
    return FLOW_NAME_WHEN_TAKEN if taken else FLOW_NAME


async def _search_flows(epicstaff: OrgClient, text: str) -> list[dict[str, Any]]:
    # EpicStaff's search matches the text in a flow's name or description.
    page = await epicstaff.get("graph-light/", params={"search": text, "limit": FLOW_LOOKUP_LIMIT})
    return page["results"]


def flow_contents(graph_id: int, save_version: int, now: datetime) -> dict[str, Any]:
    """Return the bulk save that fills an empty flow: its nodes, edges and schedule."""
    start, fetch, end, schedule = (str(uuid.uuid4()) for _ in range(4))
    return {
        "save_version": save_version,
        "start_node_list": [
            {
                "graph": graph_id,
                "temp_id": start,
                "variables": {"variables": {"city": DEFAULT_CITY, "forecast": None}},
                "metadata": {"position": {"x": 0, "y": 0}},
            }
        ],
        "python_node_list": [
            {
                "graph": graph_id,
                "temp_id": fetch,
                "node_name": FETCH_NODE_NAME,
                "input_map": {"city": "variables.city"},
                "output_variable_path": "variables.forecast",
                "python_code": {
                    "code": FETCH_FORECAST_CODE,
                    "entrypoint": "main",
                    "libraries": [],
                },
                "metadata": {"position": {"x": 320, "y": 0}},
            }
        ],
        "end_node_list": [
            {
                "graph": graph_id,
                "temp_id": end,
                "output_map": {"forecast": "variables.forecast"},
                "metadata": {"position": {"x": 640, "y": 0}},
            }
        ],
        "schedule_trigger_node_list": [
            {
                "graph": graph_id,
                "temp_id": schedule,
                "node_name": SCHEDULE_NODE_NAME,
                "is_active": False,
                "schedule": {
                    "run_mode": "repeat",
                    "timezone": "UTC",
                    "start_date_time": now.strftime("%Y-%m-%dT06:00:00"),
                    "interval": {"every": 1, "unit": "days", "weekdays": []},
                    "end": {"type": "never"},
                },
                "metadata": {"position": {"x": 0, "y": 200}},
            }
        ],
        "edge_list": [
            {"graph": graph_id, "start_temp_id": start, "end_temp_id": fetch},
            {"graph": graph_id, "start_temp_id": schedule, "end_temp_id": fetch},
            {"graph": graph_id, "start_temp_id": fetch, "end_temp_id": end},
        ],
    }
