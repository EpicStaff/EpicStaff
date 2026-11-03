"""ISM retention policies and the index template of a domain's tiered monthly indices.

Every audit event is written to `{index.name}-{tier}-{yyyy.mm}` (see
app/repositories/index_routing.py). One ISM policy per tier makes each index read-only
once its month is over and deletes it once its retention has passed, so expiry is a
whole-index delete rather than a delete-by-query over one large index.
"""

import json

from app.domains.base import IndexSpec
from loguru import logger
from opensearchpy import AsyncOpenSearch
from opensearchpy.exceptions import ConflictError
from src.shared.retention import RETENTION_CHOICES, audit_tier

# Longest month (31 days) plus margin. An index only receives writes during its own
# month, because the month comes from receive time, so read_only can never reject a write.
_READ_ONLY_AFTER_DAYS = 33
_UNLIMITED_RETENTION_DAYS = 0
_TEMPLATE_PRIORITY = 100
_ISM_TEMPLATE_PRIORITY = 100
_ISM_POLICIES_PATH = "/_plugins/_ism/policies"
# Part of every policy's description. Bump it with any change to the policy body, so a
# change that only removes a key still differs from the stored policy (see _contains).
_POLICY_REVISION = 1


def ism_policy(index: IndexSpec, days: int) -> dict:
    """Return the ISM policy request body for the tier holding `days` of retention.

    States: `open` takes writes for the index's month; `read_only` blocks writes but stays
    searchable (an OpenSearch *closed* index is not searchable, hence the name); `delete`
    removes the index. The unlimited tier has no `delete` state and stays read-only.

    Raises:
        ValueError: `days` is not one of RETENTION_CHOICES.
    """
    tier = audit_tier(days)
    read_only_state: dict = {"name": "read_only", "actions": [{"read_only": {}}], "transitions": []}
    states = [
        {
            "name": "open",
            "actions": [],
            "transitions": [
                {
                    "state_name": "read_only",
                    "conditions": {"min_index_age": f"{_READ_ONLY_AFTER_DAYS}d"},
                }
            ],
        },
        read_only_state,
    ]
    if days != _UNLIMITED_RETENTION_DAYS:
        read_only_state["transitions"].append(
            {
                "state_name": "delete",
                "conditions": {"min_index_age": f"{days + _READ_ONLY_AFTER_DAYS}d"},
            }
        )
        states.append({"name": "delete", "actions": [{"delete": {}}], "transitions": []})

    return {
        "policy": {
            "policy_id": f"{index.ism_policy_prefix}-{tier}",
            "description": (
                f"{index.name} kept {tier}: read-only after their month, then expired "
                f"(revision {_POLICY_REVISION})."
            ),
            "default_state": "open",
            "states": states,
            "ism_template": [
                {
                    "index_patterns": [f"{index.name}-{tier}-*"],
                    "priority": _ISM_TEMPLATE_PRIORITY,
                }
            ],
        }
    }


async def ensure_index_template(client: AsyncOpenSearch, index: IndexSpec) -> None:
    """Create or overwrite the composable index template the family's indices are created from.

    A template only applies to indices created after it, so existing indices keep the
    mapping they were created with.
    """
    template = json.loads(index.mapping_path.read_text())
    await client.indices.put_index_template(
        name=index.name,
        body={
            "index_patterns": [index.read_pattern],
            "priority": _TEMPLATE_PRIORITY,
            "template": template,
        },
    )
    logger.info("Index template {!r} covers {!r}.", index.name, index.read_pattern)


async def ensure_ism_policies(client: AsyncOpenSearch, index: IndexSpec) -> None:
    """Install the ISM policy of every retention tier of `index`; safe to run on every boot.

    An unchanged policy is left alone. A changed one is overwritten, guarded by its
    seq_no and primary_term. The change applies only to indices created from then on:
    indices already managed keep the policy version they started with until an operator
    moves them with `_plugins/_ism/change_policy`.
    """
    for days in RETENTION_CHOICES:
        await _ensure_ism_policy(client, ism_policy(index, days))


async def _ensure_ism_policy(client: AsyncOpenSearch, body: dict) -> None:
    policy_id = body["policy"]["policy_id"]
    path = f"{_ISM_POLICIES_PATH}/{policy_id}"
    try:
        await client.transport.perform_request("PUT", path, body=body)
    except ConflictError:
        pass
    else:
        logger.info("Created ISM policy {!r}.", policy_id)
        return

    current = await client.transport.perform_request("GET", path)
    if _contains(current["policy"], body["policy"]):
        logger.info("ISM policy {!r} is up to date.", policy_id)
        return

    try:
        await client.transport.perform_request(
            "PUT",
            path,
            body=body,
            params={"if_seq_no": current["_seq_no"], "if_primary_term": current["_primary_term"]},
        )
    except ConflictError:
        # Another replica wrote the policy between our GET and this PUT. With replicas of
        # the same version it wrote the same body. During a rolling deploy an old and a new
        # auditor overwrite each other's version on every boot until all replicas run the
        # new one, and an index created in that window attaches whichever version is
        # stored at that moment (fix it afterwards with `_plugins/_ism/change_policy`).
        logger.info("ISM policy {!r} was updated concurrently by another replica.", policy_id)
        return
    logger.info("Updated ISM policy {!r}.", policy_id)


def _contains(actual, expected) -> bool:
    """Whether `actual` holds everything `expected` does.

    The server stores more than was sent (per-action `retry`, `last_updated_time`,
    `schema_version`), so extra dict keys on the server side are not a difference.
    Lists must match element by element, so an added or removed state or transition is.

    Blind spot: a key removed from the desired policy is never detected, because the
    stored policy still having it looks like a server-added field. _POLICY_REVISION in
    the description covers that: bumping it makes every changed policy differ.
    """
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and _contains(actual[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(_contains(item, wanted) for item, wanted in zip(actual, expected, strict=True))
        )
    return actual == expected
