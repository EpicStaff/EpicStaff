from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.problems import MANIFEST_LOC, Problem
from rbac.access.bitmask import actions_to_bitmask
from rbac.access.catalog import applicable_actions_for, grantable_bits_for


def declared_access_problems(manifest: PluginManifest) -> list[Problem]:
    """Check the manifest's `access` against this EpicStaff's permission catalog.

    Every resource type must exist here, and every action must be one that type has and a
    role could be granted. The manifest model checks only the form of `access`, because the
    catalog differs between EpicStaff versions.
    """
    problems = []
    for index, declaration in enumerate(manifest.access):
        loc = f"{MANIFEST_LOC}.access[{index}]"
        applicable = applicable_actions_for(declaration.resource_type)
        if not applicable:
            problems.append(
                Problem(
                    f"{loc}.resource_type",
                    f"'{declaration.resource_type}' is not a resource type of this EpicStaff",
                )
            )
            continue
        grantable = grantable_bits_for(declaration.resource_type)
        problems.extend(
            Problem(
                f"{loc}.actions[{action_index}]",
                f"'{action}' is not an action of {declaration.resource_type}",
            )
            for action_index, action in enumerate(declaration.actions)
            if action not in applicable or not actions_to_bitmask([action]) & grantable
        )
    return problems
