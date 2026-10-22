"""What a SuperAdmin is warned about when reviewing a package."""

from collections.abc import Mapping
from types import MappingProxyType

from epicstaff_plugin.contracts.manifest import WILDCARD_HOST_PREFIX, PluginManifest
from rbac.access.catalog import ACTION_METADATA, RESOURCE_TYPE_METADATA
from rbac.models.enums import ResourceType

from plugins.models import Trust

UNTRUSTED_PACKAGE = "untrusted_package"
RUNS_CODE_IN_SANDBOX = "runs_code_in_sandbox"
FLOWS_USE_MISSING = "flows_use_missing"
WILDCARD_OUTBOUND_HOST = "wildcard_outbound_host"
# The access through which a plugin gets Python of its choosing run in EpicStaff's sandbox, whose
# network is its own, so the plugin's outbound hosts do not bound that code. Flows: a flow's nodes
# hold code, testing a node runs it (flows update), and running a flow runs all of it. Tools: a
# Python tool's code runs whenever an agent calls the tool. No other declarable resource stores
# code that the sandbox or an agent runs; a resource that comes to do so belongs here.
ACTIONS_THAT_RUN_CODE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        ResourceType.FLOWS.value: frozenset({"create", "update", "use"}),
        ResourceType.TOOLS.value: frozenset({"create", "update"}),
    }
)

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
    declared = {
        declaration.resource_type: frozenset(declaration.actions) for declaration in manifest.access
    }
    running_code = [
        resource_label(resource_type).lower()
        for resource_type, actions in ACTIONS_THAT_RUN_CODE.items()
        if actions & declared.get(resource_type, frozenset())
    ]
    if running_code:
        warnings.append(
            {
                "code": RUNS_CODE_IN_SANDBOX,
                "message": (
                    f"Through {_spoken_list(running_code)}, the plugin can have code of its "
                    "choosing run in EpicStaff's sandbox, which has its own network access. The "
                    "plugin's outbound hosts do not apply to that code."
                ),
            }
        )
    flows_actions = declared.get(ResourceType.FLOWS.value, frozenset())
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


def _spoken_list(items: list[str]) -> str:
    """`a`, `a and b`, `a, b and c`."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
