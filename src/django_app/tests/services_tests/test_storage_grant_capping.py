"""Limiting imported or copied grant flags to what the actor may hand out (pure rules)."""

import pytest
from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType

from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
)
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.capping import cap_grant_data

FLAGS = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")


def _actor(files: int) -> GrantActor:
    permissions = EffectivePermissions(
        is_superadmin=False, role=None, by_resource={ResourceType.FILES.value: files}
    )
    return GrantActor(lambda: permissions)


EVERYTHING = _actor(
    Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE
)
READ_ONLY = _actor(Permission.READ)
NOTHING = _actor(0)


def _cap(data, actor, model=PythonNode):
    return cap_grant_data(data, actor, model=model)


@pytest.mark.parametrize(
    ("data", "actor", "expected"),
    [
        pytest.param({}, EVERYTHING, dict.fromkeys(FLAGS, True), id="missing-keys-read-as-ticked"),
        pytest.param(dict.fromkeys(FLAGS), EVERYTHING, dict.fromkeys(FLAGS, True), id="null-reads-as-ticked"),
        pytest.param(
            dict.fromkeys(FLAGS),
            READ_ONLY,
            dict(zip(FLAGS, (True, False, False), strict=True)),
            id="null-becomes-what-the-actor-holds",
        ),
        pytest.param(
            {},
            READ_ONLY,
            dict(zip(FLAGS, (True, False, False), strict=True)),
            id="missing-keys-become-what-the-actor-holds",
        ),
        pytest.param(
            {"storage_grant_write": False},
            EVERYTHING,
            dict(zip(FLAGS, (True, False, True), strict=True)),
            id="a-flag-that-is-present-is-not-read-as-ticked",
        ),
        pytest.param(dict.fromkeys(FLAGS), NOTHING, dict.fromkeys(FLAGS, False), id="null-for-nobody"),
        pytest.param(dict.fromkeys(FLAGS), None, dict.fromkeys(FLAGS, False), id="null-without-an-actor"),
        pytest.param(
            dict.fromkeys(FLAGS, True),
            READ_ONLY,
            dict(zip(FLAGS, (True, False, False), strict=True)),
            id="set-flags-are-lowered",
        ),
        pytest.param(
            dict.fromkeys(FLAGS, True), EVERYTHING, dict.fromkeys(FLAGS, True), id="held-flags-stay"
        ),
        pytest.param(
            dict.fromkeys(FLAGS, False), NOTHING, dict.fromkeys(FLAGS, False), id="off-stays-off"
        ),
    ],
)
def test_a_slot_is_limited_to_what_the_actor_may_hand_out(data, actor, expected):
    assert {key: value for key, value in _cap(data, actor).items() if key in FLAGS} == expected


def test_missing_flags_read_as_ticked_then_capped():
    member = _actor(Permission.READ | Permission.CREATE | Permission.UPDATE)

    capped = _cap({"node_name": "legacy"}, member)

    assert {name: capped[name] for name in FLAGS} == {
        "storage_grant_read": True,
        "storage_grant_write": True,
        "storage_grant_delete": False,
    }


@pytest.mark.parametrize("model", [FileExtractorNode, AudioTranscriptionNode])
def test_a_file_node_has_no_grant_flags_to_cap(model):
    assert _cap({"node_name": "reader"}, EVERYTHING, model=model) == {"node_name": "reader"}


@pytest.mark.parametrize("truthy", ["true", "True", "1", 1, "on", "yes", "t", "Y"])
def test_a_value_the_serializer_reads_as_true_is_capped_too(truthy):
    capped = _cap({name: truthy for name in FLAGS}, NOTHING)

    assert [capped[name] for name in FLAGS] == [False, False, False]


def test_other_keys_are_left_alone_and_other_models_get_no_flags():
    data = {"node_name": "n", "input_map": {"a": 1}}

    assert _cap(data, NOTHING, model=PythonNode)["node_name"] == "n"
    assert _cap(data, NOTHING, model=dict) == data


def test_each_code_slot_of_a_classification_table_is_capped_on_its_own():
    data = {
        "pre_storage_grant_read": True,
        "pre_storage_grant_write": True,
        "pre_storage_grant_delete": True,
        "post_storage_grant_read": False,
        "post_storage_grant_write": False,
        "post_storage_grant_delete": False,
    }

    capped = _cap(data, READ_ONLY, model=ClassificationDecisionTableNode)

    assert [capped[f"pre_{name}"] for name in FLAGS] == [True, False, False]
    assert [capped[f"post_{name}"] for name in FLAGS] == [False, False, False]
