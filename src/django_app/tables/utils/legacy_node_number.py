import re

_TRAILING_BADGE = re.compile(r"\s*#\s*(\d+)\s*$")
# Same bound as the backfill migration: far above any real badge, so a name such as
# "Order #20240101123456" keeps its digits, and node_number_seq stays far from int32 overflow.
MAX_BADGE_NUMBER = 1_000_000


def _badge_number_or_none(number: object) -> int | None:
    # Exact type match: bool is a subclass of int and is not a badge number.
    if type(number) is int and 1 <= number <= MAX_BADGE_NUMBER:
        return number
    return None


def split_legacy_node_name(node_name: str, metadata_number: object) -> tuple[str, int | None]:
    """Split a pre-column node name such as "Python-Node #3" into its label and badge number.

    The badge comes from `metadata_number` when it is a valid badge, else from the
    "#N" name suffix. The suffix is removed only when it is that badge and a label
    remains, so "Step #2" on node #5 stays as the user typed it. A number outside
    1..MAX_BADGE_NUMBER counts as no number.
    """
    number = _badge_number_or_none(metadata_number)
    match = _TRAILING_BADGE.search(node_name or "")
    if match is None:
        return node_name, number
    suffix_number = _badge_number_or_none(int(match.group(1)))
    if number is None:
        number = suffix_number
    label = node_name[: match.start()]
    if number is None or suffix_number != number or not label.strip():
        return node_name, number
    return label, number


def move_legacy_badge_into_node_number(node: dict) -> None:
    """Rewrite one exported node of the pre-column format in place.

    The badge leaves the name and metadata["nodeNumber"] and becomes node_number.
    A node that already has a node_number key is in the current format and is left
    untouched, so running this twice changes nothing; a node without a name has no
    badge to move.
    """
    if "node_number" in node or "node_name" not in node:
        return
    metadata = node.get("metadata")
    metadata_number = metadata.pop("nodeNumber", None) if isinstance(metadata, dict) else None
    node["node_name"], node["node_number"] = split_legacy_node_name(
        node["node_name"], metadata_number
    )
