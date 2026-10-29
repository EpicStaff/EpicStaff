"""Index setup on auditor boot: ISM policies, the index template, and the legacy index drop.

Runs against FakeCluster, an in-memory stand-in for the few OpenSearch APIs the setup
calls. It answers the way OpenSearch 2.19 does where the setup depends on it: an
unconditional PUT of an existing ISM policy is a 409, a conditional PUT with a stale
seq_no is a 409, and a GET returns the server-added fields (retry, last_updated_time,
schema_version) next to the stored policy.
"""

import copy

import pytest
from loguru import logger
from opensearchpy.exceptions import ConflictError, NotFoundError

from app.index_setup.runner import setup_indices

POLICY_IDS = {
    "audit-retention-unlimited",
    "audit-retention-30d",
    "audit-retention-90d",
    "audit-retention-180d",
    "audit-retention-365d",
}
_POLICY_PATH_PREFIX = "/_plugins/_ism/policies/"
_DEFAULT_RETRY = {"count": 3, "backoff": "exponential", "delay": "1m"}


def _version_conflict() -> ConflictError:
    return ConflictError(
        409,
        "version_conflict_engine_exception",
        {"error": {"type": "version_conflict_engine_exception"}, "status": 409},
    )


def _as_stored_by_server(policy_id: str, policy: dict) -> dict:
    stored = copy.deepcopy(policy)
    stored.update(
        policy_id=policy_id,
        last_updated_time=1760000000000,
        schema_version=21,
        error_notification=None,
    )
    for state in stored["states"]:
        for action in state["actions"]:
            action.setdefault("retry", dict(_DEFAULT_RETRY))
    for template in stored.get("ism_template") or []:
        template["last_updated_time"] = 1760000000000
    return stored


class _FakeTransport:
    def __init__(self, cluster: "FakeCluster"):
        self._cluster = cluster

    async def perform_request(self, method, url, params=None, body=None, **kwargs):
        assert url.startswith(_POLICY_PATH_PREFIX), url
        policy_id = url.removeprefix(_POLICY_PATH_PREFIX)
        if method == "GET":
            return self._cluster.get_policy(policy_id)
        if method == "PUT":
            return self._cluster.put_policy(policy_id, body, params or {})
        raise AssertionError(f"unexpected {method} {url}")


class _FakeIndices:
    def __init__(self, cluster: "FakeCluster"):
        self._cluster = cluster

    async def put_index_template(self, name, body, **kwargs):
        self._cluster.operations.append(("put_index_template", name))
        self._cluster.templates[name] = copy.deepcopy(body)
        return {"acknowledged": True}

    async def exists(self, index, **kwargs):
        return index in self._cluster.indices or index in self._cluster.aliases

    async def get(self, index, **kwargs):
        self._cluster.vanish_if_due("get", index)
        if index in self._cluster.indices:
            return {index: {}}
        if index in self._cluster.aliases:
            target = self._cluster.aliases[index]
            return {target: {"aliases": {index: {}}}}
        raise NotFoundError(404, "index_not_found_exception", {})

    async def delete(self, index, **kwargs):
        self._cluster.vanish_if_due("delete", index)
        if index not in self._cluster.indices:
            raise NotFoundError(404, "index_not_found_exception", {})
        self._cluster.operations.append(("delete_index", index))
        del self._cluster.indices[index]
        return {"acknowledged": True}


class FakeCluster:
    def __init__(
        self,
        *,
        indices: dict[str, int] | None = None,
        aliases: dict[str, str] | None = None,
    ):
        self.indices = dict(indices or {})
        self.aliases = dict(aliases or {})
        self.templates: dict[str, dict] = {}
        self.policies: dict[str, dict] = {}
        self.operations: list[tuple[str, str]] = []
        self.write_between_get_and_put = False
        # Name of the step ("get", "count", "delete") right before which another replica
        # deletes the index being worked on.
        self.vanish_before: str | None = None
        self._seq_no = 0
        self.transport = _FakeTransport(self)
        self.indices_api = _FakeIndices(self)

    def vanish_if_due(self, step: str, index: str) -> None:
        if self.vanish_before == step:
            self.indices.pop(index, None)

    async def count(self, index, **kwargs):
        self.vanish_if_due("count", index)
        if index not in self.indices:
            raise NotFoundError(404, "index_not_found_exception", {})
        return {"count": self.indices[index]}

    def _next_seq_no(self) -> int:
        self._seq_no += 1
        return self._seq_no

    def get_policy(self, policy_id: str) -> dict:
        if policy_id not in self.policies:
            raise NotFoundError(404, "status_exception", {})
        record = self.policies[policy_id]
        response = {
            "_id": policy_id,
            "_seq_no": record["_seq_no"],
            "_primary_term": record["_primary_term"],
            "policy": copy.deepcopy(record["policy"]),
        }
        if self.write_between_get_and_put:
            record["_seq_no"] = self._next_seq_no()
        return response

    def put_policy(self, policy_id: str, body: dict, params: dict) -> dict:
        existing = self.policies.get(policy_id)
        if existing is None and "if_seq_no" in params:
            raise NotFoundError(404, "document_missing_exception", {})
        if existing is not None:
            if "if_seq_no" not in params:
                raise _version_conflict()
            if (int(params["if_seq_no"]), int(params["if_primary_term"])) != (
                existing["_seq_no"],
                existing["_primary_term"],
            ):
                raise _version_conflict()
        self.operations.append(("put_policy", policy_id))
        self.policies[policy_id] = {
            "_seq_no": self._next_seq_no(),
            "_primary_term": 1,
            "policy": _as_stored_by_server(policy_id, body["policy"]),
        }
        return {"_id": policy_id}

    def seq_nos(self) -> dict[str, int]:
        return {policy_id: record["_seq_no"] for policy_id, record in self.policies.items()}


class FakeClient:
    """Exposes FakeCluster under the attribute names AsyncOpenSearch uses."""

    def __init__(self, cluster: FakeCluster):
        self.indices = cluster.indices_api
        self.transport = cluster.transport
        self.count = cluster.count


@pytest.fixture
def warnings():
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


def _delete_age(cluster: FakeCluster, policy_id: str) -> str:
    states = {state["name"]: state for state in cluster.policies[policy_id]["policy"]["states"]}
    return states["read_only"]["transitions"][0]["conditions"]["min_index_age"]


@pytest.mark.asyncio
async def test_runner_installs_template_and_five_policies():
    cluster = FakeCluster()

    await setup_indices(FakeClient(cluster))

    assert set(cluster.policies) == POLICY_IDS
    template = cluster.templates["audit_events"]
    assert template["index_patterns"] == ["audit_events-*"]
    assert template["template"]["mappings"]["properties"]["retention_days"] == {"type": "integer"}
    assert template["template"]["mappings"]["properties"]["event_time"] == {"type": "date"}
    assert template["template"]["settings"]["number_of_shards"] == 1
    assert template["template"]["settings"]["auto_expand_replicas"] == "0-1"
    template_position = cluster.operations.index(("put_index_template", "audit_events"))
    policy_positions = [
        position for position, (operation, _) in enumerate(cluster.operations)
        if operation == "put_policy"
    ]
    assert len(policy_positions) == 5
    assert max(policy_positions) < template_position


@pytest.mark.asyncio
async def test_runner_is_idempotent():
    cluster = FakeCluster()
    await setup_indices(FakeClient(cluster))
    seq_nos_after_first_run = cluster.seq_nos()

    await setup_indices(FakeClient(cluster))

    assert cluster.seq_nos() == seq_nos_after_first_run


@pytest.mark.asyncio
async def test_a_changed_policy_is_updated_with_its_seq_no_and_primary_term():
    cluster = FakeCluster()
    await setup_indices(FakeClient(cluster))
    outdated = cluster.policies["audit-retention-90d"]
    states = {state["name"]: state for state in outdated["policy"]["states"]}
    states["read_only"]["transitions"][0]["conditions"]["min_index_age"] = "100d"
    seq_nos_before = cluster.seq_nos()

    await setup_indices(FakeClient(cluster))

    assert _delete_age(cluster, "audit-retention-90d") == "123d"
    changed = {
        policy_id for policy_id, seq_no in cluster.seq_nos().items()
        if seq_no != seq_nos_before[policy_id]
    }
    assert changed == {"audit-retention-90d"}


@pytest.mark.asyncio
async def test_setup_completes_when_another_replica_writes_a_policy_between_get_and_put():
    cluster = FakeCluster()
    await setup_indices(FakeClient(cluster))
    states = {
        state["name"]: state
        for state in cluster.policies["audit-retention-30d"]["policy"]["states"]
    }
    states["read_only"]["transitions"][0]["conditions"]["min_index_age"] = "1d"
    cluster.write_between_get_and_put = True

    await setup_indices(FakeClient(cluster))

    assert "audit_events" in cluster.templates


@pytest.mark.asyncio
async def test_legacy_single_index_is_dropped_once(warnings):
    cluster = FakeCluster(indices={"audit_events": 1044})

    await setup_indices(FakeClient(cluster))
    await setup_indices(FakeClient(cluster))

    assert "audit_events" not in cluster.indices
    assert cluster.operations.count(("delete_index", "audit_events")) == 1
    assert any("audit_events" in message and "1044" in message for message in warnings)
    assert "audit_events" in cluster.templates


@pytest.mark.asyncio
async def test_tiered_indices_are_not_touched_when_the_legacy_index_is_absent():
    cluster = FakeCluster(indices={"audit_events-90d-2026.10": 5})

    await setup_indices(FakeClient(cluster))

    assert cluster.indices == {"audit_events-90d-2026.10": 5}
    assert not [operation for operation in cluster.operations if operation[0] == "delete_index"]


@pytest.mark.asyncio
async def test_an_alias_named_like_the_legacy_index_is_left_alone_and_does_not_block_setup():
    cluster = FakeCluster(
        indices={"audit_events-unlimited-2026.10": 3},
        aliases={"audit_events": "audit_events-unlimited-2026.10"},
    )

    await setup_indices(FakeClient(cluster))

    assert cluster.indices == {"audit_events-unlimited-2026.10": 3}
    assert "audit_events" in cluster.templates
    assert set(cluster.policies) == POLICY_IDS


@pytest.mark.asyncio
async def test_a_transition_removed_from_the_desired_policy_is_removed_from_the_stored_one():
    cluster = FakeCluster()
    await setup_indices(FakeClient(cluster))
    stored = cluster.policies["audit-retention-unlimited"]["policy"]
    states = {state["name"]: state for state in stored["states"]}
    states["read_only"]["transitions"].append(
        {"state_name": "delete", "conditions": {"min_index_age": "33d"}}
    )

    await setup_indices(FakeClient(cluster))

    states = {
        state["name"]: state
        for state in cluster.policies["audit-retention-unlimited"]["policy"]["states"]
    }
    assert states["read_only"]["transitions"] == []


@pytest.mark.parametrize("step", ["get", "count", "delete"])
@pytest.mark.asyncio
async def test_legacy_index_deleted_by_another_replica_midway_does_not_fail_setup(step):
    cluster = FakeCluster(indices={"audit_events": 1044})
    cluster.vanish_before = step

    await setup_indices(FakeClient(cluster))

    assert "audit_events" not in cluster.indices
    assert "audit_events" in cluster.templates
