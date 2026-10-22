"""What a SuperAdmin is warned about when reviewing a package."""

from epicstaff_plugin.contracts.manifest import WILDCARD_HOST_PREFIX, PluginManifest
from rbac.access.catalog import ACTION_METADATA, RESOURCE_TYPE_METADATA
from rbac.models.enums import ResourceType

from plugins.models import Trust

UNTRUSTED_PACKAGE = "untrusted_package"
FLOWS_RUN_CODE = "flows_run_code"
FLOWS_USE_MISSING = "flows_use_missing"
WILDCARD_OUTBOUND_HOST = "wildcard_outbound_host"
# The flows actions through which a plugin gets Python run in EpicStaff's sandbox: writing a
# flow's code, or running a flow. The sandbox's network is its own; outbound hosts do not bound it.
FLOWS_ACTIONS_THAT_RUN_CODE = frozenset({"create", "update", "use"})

_ACTION_LABELS = {entry["code"]: entry["label"] for entry in ACTION_METADATA}
_RESOURCE_LABELS = {entry["code"]: entry["label"] for entry in RESOURCE_TYPE_METADATA}


def action_label(action: str) -> str:
    """The name the permission matrix shows for an action (`read` is View, `update` is Edit)."""
    return _ACTION_LABELS[action]


def resource_label(resource_type: str) -> str:
    return _RESOURCE_LABELS.get(resource_type, resource_type)


def review_warnings(manifest: PluginManifest, trust: str) -> list[dict[str, str]]:
    """Return the warnings shown next to a package's review, as `{code, message}`.

    The same for a first install and for an upgrade: both review the package itself.
    """
    warnings = []
    if trust == Trust.UNTRUSTED:
        warnings.append(
            {
                "code": UNTRUSTED_PACKAGE,
                "message": (
                    "This package is not signed by a key this deployment trusts. Installing it "
                    "runs code nobody here has verified, with the access listed below."
                ),
            }
        )
    flows = next(
        (
            declaration
            for declaration in manifest.access
            if declaration.resource_type == ResourceType.FLOWS
        ),
        None,
    )
    flows_actions = set(flows.actions) if flows else set()
    if FLOWS_ACTIONS_THAT_RUN_CODE & flows_actions:
        warnings.append(
            {
                "code": FLOWS_RUN_CODE,
                "message": (
                    "Through flows, the plugin can run code in EpicStaff's sandbox, which has "
                    "its own network access. The plugin's outbound hosts do not apply to that "
                    "code."
                ),
            }
        )
    if {"create", "update"} & flows_actions and "use" not in flows_actions:
        warnings.append(
            {
                "code": FLOWS_USE_MISSING,
                "message": (
                    "The plugin may create or edit flows but not use them: it cannot run a "
                    "flow itself or write schedule, webhook or Telegram trigger nodes. A flow "
                    "it writes still runs, with its code, when someone in the organization "
                    "runs it."
                ),
            }
        )
    warnings.extend(
        {
            "code": WILDCARD_OUTBOUND_HOST,
            "message": f"The plugin may call every subdomain of {outbound.host.removeprefix(WILDCARD_HOST_PREFIX)}.",
        }
        for outbound in manifest.outbound_hosts
        if outbound.host.startswith(WILDCARD_HOST_PREFIX)
    )
    return warnings
