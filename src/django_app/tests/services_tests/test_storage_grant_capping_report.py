"""What capping reports as dropped: the boxes the actor's permissions unticked (pure rules)."""

import pytest
from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType
from src.shared.models.storage_scope import StorageAction

from tables.models.graph_models import ClassificationDecisionTableNode, PythonNode
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.capping import (
    DroppedGrants,
    cap_grant_data,
    cap_grant_data_reporting,
)

FLAGS = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")


def _actor(files: int) -> GrantActor:
    permissions = EffectivePermissions(
        is_superadmin=False, role=None, by_resource={ResourceType.FILES.value: files}
    )
    return GrantActor(lambda: permissions)


EVERYTHING = _actor(Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE)
MEMBER = _actor(Permission.READ | Permission.CREATE | Permission.UPDATE)
READ_ONLY = _actor(Permission.READ)
NOTHING = _actor(0)


def _report(data, actor, model=PythonNode):
    return cap_grant_data_reporting(data, actor, model=model)[1]


@pytest.mark.parametrize(
    ("data", "actor", "expected"),
    [
        pytest.param(
            dict.fromkeys(FLAGS, True), MEMBER, [("python_code", ("delete",))], id="delete"
        ),
        pytest.param({}, MEMBER, [("python_code", ("delete",))], id="missing-boxes-read-as-ticked"),
        pytest.param(
            dict.fromkeys(FLAGS, True),
            READ_ONLY,
            [("python_code", ("write", "delete"))],
            id="ordered-read-write-delete",
        ),
        pytest.param(dict.fromkeys(FLAGS, True), EVERYTHING, [], id="holding-everything"),
        pytest.param(
            dict.fromkeys(FLAGS, True),
            None,
            [("python_code", ("read", "write", "delete"))],
            id="no-actor",
        ),
        pytest.param(dict.fromkeys(FLAGS, False), NOTHING, [], id="unticked-boxes-lose-nothing"),
        pytest.param(
            {"use_storage": False, **dict.fromkeys(FLAGS, True)},
            NOTHING,
            [],
            id="switch-off-is-not-a-drop",
        ),
    ],
)
def test_capping_reports_the_boxes_the_actors_permissions_dropped(data, actor, expected):
    assert [
        (dropped.code_field, tuple(action.value for action in dropped.actions))
        for dropped in _report(data, actor)
    ] == expected


def test_capping_reports_each_classification_slot_under_its_own_code_field():
    data = {
        "pre_storage_grant_read": True,
        "pre_storage_grant_write": False,
        "pre_storage_grant_delete": False,
        "post_storage_grant_read": False,
        "post_storage_grant_write": False,
        "post_storage_grant_delete": True,
    }

    dropped = _report(data, MEMBER, ClassificationDecisionTableNode)

    assert dropped == [DroppedGrants("post_python_code", (StorageAction.DELETE,))]


def test_a_switch_that_is_off_only_in_one_classification_slot_reports_the_other():
    data = {"pre_use_storage": False, "post_use_storage": True}

    dropped = _report(data, MEMBER, ClassificationDecisionTableNode)

    assert dropped == [DroppedGrants("post_python_code", (StorageAction.DELETE,))]


def test_reporting_returns_the_same_data_as_capping():
    data = dict.fromkeys(FLAGS, True)

    capped, _ = cap_grant_data_reporting(data, MEMBER, model=PythonNode)

    assert capped == cap_grant_data(data, MEMBER, model=PythonNode)
