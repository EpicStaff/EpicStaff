"""The deployment's plugin node, registered from the environment at every start."""

import re
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from src.shared.models.plugin_nodes import NODE_PORT_RANGE

from plugins.models import PluginNode
from plugins.nodes.node_authentication import node_key_hash

# The service name the node runs under in compose, on the plugins network.
NODE_INTERNAL_HOST = "es_plugins"
UNCONFIGURED_KEY = "none"
# Above the node agent's own user id (10000), below the ids desktop systems hand out.
MIN_UID_EXCLUSIVE = 10000
MAX_UID_EXCLUSIVE = 60000
MIN_UID_COUNT = 10
_UID_RANGE = re.compile(r"^([0-9]{1,5})-([0-9]{1,5})$")


@dataclass(frozen=True)
class UidRange:
    start: int
    end: int


def parse_uid_range(text: str) -> UidRange | None:
    """Return the `<start>-<end>` user id range, or None when it breaks a rule.

    The rules: 10000 < start <= end < 60000, and at least 10 ids.
    """
    match = _UID_RANGE.fullmatch((text or "").strip())
    if match is None:
        return None
    start, end = int(match.group(1)), int(match.group(2))
    if (
        not (MIN_UID_EXCLUSIVE < start <= end < MAX_UID_EXCLUSIVE)
        or end - start + 1 < MIN_UID_COUNT
    ):
        return None
    return UidRange(start=start, end=end)


def register_configured_node() -> PluginNode | None:
    """Create or update the node named PLUGINS_NODE_NAME from the environment.

    Every other node loses its key, so a node renamed or replaced in the environment can no
    longer authenticate with the key it had. Does nothing (returns None) while the platform
    is off or PLUGINS_NODE_KEY is `none`. The plugins.E007 and plugins.E008 start-up checks
    have already refused a malformed key or user id range while the platform is on.
    """
    key = settings.PLUGINS_NODE_KEY
    if not settings.PLUGINS_ENABLED or not key or key == UNCONFIGURED_KEY:
        return None
    uid_range = parse_uid_range(settings.PLUGINS_NODE_UID_RANGE)
    if uid_range is None:
        raise ValueError(f"PLUGINS_NODE_UID_RANGE {settings.PLUGINS_NODE_UID_RANGE!r} is invalid")
    key_hash = node_key_hash(key)
    with transaction.atomic():
        # Cleared first: the key's hash is unique across nodes.
        PluginNode.objects.exclude(name=settings.PLUGINS_NODE_NAME).update(key_hash=None)
        node, _ = PluginNode.objects.update_or_create(
            name=settings.PLUGINS_NODE_NAME,
            defaults={
                "key_hash": key_hash,
                "internal_host": NODE_INTERNAL_HOST,
                "port_range_start": NODE_PORT_RANGE[0],
                "port_range_end": NODE_PORT_RANGE[1],
                "uid_range_start": uid_range.start,
                "uid_range_end": uid_range.end,
            },
        )
    return node
