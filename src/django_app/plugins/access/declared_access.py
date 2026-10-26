"""What a plugin's backend may do in EpicStaff: the manifest's `access`, in permission bits.

The service account of a grant holds exactly these bits in the grant's organization, and
nothing anywhere else. They come from the package, so they never change for a package and
are worked out once per package id in each process.
"""

import threading

from epicstaff_plugin.contracts.manifest import PluginManifest
from epicstaff_plugin.problems import MANIFEST_LOC, Problem
from rbac.access.bitmask import actions_to_bitmask
from rbac.access.catalog import applicable_actions_for, grantable_bits_for
from rbac.models.enums import ResourceType

from plugins.models import PluginPackage

# Their endpoints never accept a plugin credential (they are pinned to people's credentials
# or live in another service), so declaring them would grant nothing and mislead the review.
NON_DECLARABLE_RESOURCE_TYPES = frozenset(
    {
        ResourceType.ORGANIZATIONS.value,
        ResourceType.MEMBERSHIPS.value,
        ResourceType.ROLES.value,
        ResourceType.API_KEYS.value,
        ResourceType.AUDIT.value,
        ResourceType.CHATS.value,
    }
)


def declared_access_problems(manifest: PluginManifest) -> list[Problem]:
    """Check the manifest's `access` against this EpicStaff's permission catalog.

    Every resource type must exist here and be one a plugin may declare, and every action
    must be one that type has and a role could be granted. The manifest model checks only
    the form of `access`, because the catalog differs between EpicStaff versions.
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
        if declaration.resource_type in NON_DECLARABLE_RESOURCE_TYPES:
            problems.append(
                Problem(
                    f"{loc}.resource_type",
                    f"'{declaration.resource_type}' cannot be declared by a plugin",
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


def declared_access_bits(manifest: PluginManifest) -> dict[str, int]:
    """Return the declared access as a bitmask per resource type, within what is grantable.

    A declaration the catalog no longer allows (a resource type that became non-declarable
    after the upload) grants nothing.
    """
    return {
        declaration.resource_type: actions_to_bitmask(declaration.actions)
        & grantable_bits_for(declaration.resource_type)
        for declaration in manifest.access
        if declaration.resource_type not in NON_DECLARABLE_RESOURCE_TYPES
    }


class _BitsByPackage:
    def __init__(self):
        self._bits: dict[int, dict[str, int]] = {}
        self._lock = threading.Lock()

    def get(self, package: PluginPackage) -> dict[str, int]:
        with self._lock:
            bits = self._bits.get(package.pk)
        if bits is None:
            bits = declared_access_bits(package.parsed_manifest)
            with self._lock:
                self._bits[package.pk] = bits
        return dict(bits)

    def clear(self) -> None:
        with self._lock:
            self._bits.clear()


package_declared_access_bits = _BitsByPackage()
