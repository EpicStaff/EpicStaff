"""The upgrade hook: what Weather does in an organization that moves to this version.

EpicStaff calls it once per organization, after this version has started and its migrations
ran, with the version the organization was last brought to in `previous_version`. That may be
several versions back, so the hook brings an organization from any earlier version: it runs
the install hook's steps again, which create what is missing and bring the forecast flow to
this version's description and code. Organizations already at `FLOW_VERSION` or later have
nothing to change. A null `previous_version` means the organization never finished an earlier
install, so it gets everything, as from scratch.

It runs as the plugin alone, with the organization's service account, while the organization
waits as "Upgrading…". Raising fails the hook with the exception's message; EpicStaff tries it
again after 1 and after 5 minutes, then waits for a SuperAdmin's Retry. Every step looks up what
an earlier attempt made first, so running it twice is harmless.
"""

from epicstaff_plugin.client import OrgClient
from epicstaff_plugin.contracts.hook_api import HookRequest
from epicstaff_plugin.hooks import hook_registry
from epicstaff_plugin.versions import is_newer

from weather_plugin.forecast_flow import FLOW_VERSION, ensure_forecast_flow
from weather_plugin.install_hook import ensure_readme


@hook_registry.on_upgrade
async def upgrade(request: HookRequest, epicstaff: OrgClient) -> None:
    """Bring the organization's flow and readme to this version, unless it already has them."""
    previous_version = request.previous_version
    if previous_version is not None and not is_newer(FLOW_VERSION, previous_version):
        return
    await ensure_forecast_flow(epicstaff)
    await ensure_readme(epicstaff)
