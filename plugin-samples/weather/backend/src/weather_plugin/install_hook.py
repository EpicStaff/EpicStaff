"""The install hook: what Weather sets up in an organization it is granted to.

EpicStaff calls it once per grant, before anyone in the organization can open Weather. It
runs as the plugin alone, with the organization's service account, so EpicStaff records the
flow and the file as owned by Weather. Raising fails the hook with the exception's message,
and a SuperAdmin can retry it: every step looks up what an earlier attempt made first.
"""

from epicstaff_plugin.client import EpicStaffApiError, OrgClient
from epicstaff_plugin.contracts.hook_api import HookRequest
from epicstaff_plugin.hooks import hook_registry

from weather_plugin.forecast_flow import ensure_forecast_flow

README_FOLDER = "weather"
README_NAME = "README.md"
README_TEXT = """\
# Weather

The Weather plugin keeps its files in this folder.

- The flow "Weather forecast" fetches a seven-day forecast for `variables.city` from
  Open-Meteo. Weather runs it when someone asks for a forecast on its Forecast page.
- Its schedule trigger "Every day at 06:00 UTC" is created inactive. Turn it on in the
  flow editor to fetch the forecast for the flow's default city every morning.
"""


@hook_registry.on_install
async def install(request: HookRequest, epicstaff: OrgClient) -> None:
    """Create the forecast flow and the readme in the organization, where they are missing."""
    await ensure_forecast_flow(epicstaff)
    await ensure_readme(epicstaff)


async def ensure_readme(epicstaff: OrgClient) -> None:
    """Upload `weather/README.md` unless the organization's storage already has it.

    Raises:
        EpicStaffApiError: EpicStaff refused a call other than the lookup's "not found".
    """
    try:
        await epicstaff.get("storage/info/", params={"path": f"{README_FOLDER}/{README_NAME}"})
        return
    except EpicStaffApiError as error:
        if error.status != 404:
            raise
    await epicstaff.upload_file(README_FOLDER, README_NAME, README_TEXT.encode("utf-8"))
