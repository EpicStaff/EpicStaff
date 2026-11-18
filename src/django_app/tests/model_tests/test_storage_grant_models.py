"""Database rules of the storage grant columns and of the temporary account table."""

import pytest
from django.db import IntegrityError, transaction

from storage_credentials.models import TemporaryStorageAccount
from tables.models import Graph, PythonCode, Session
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    TaskNode,
    WebhookTriggerNode,
)
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS

CASES = [
    pytest.param(model, slot, id=f"{model.__name__}-{slot.prefix or 'node'}")
    for model, slots in STORAGE_GRANT_SLOTS.items()
    for slot in slots
]


def _create(model, graph, **flags):
    code = PythonCode.objects.create(code="x", entrypoint="main")
    extra = {
        PythonNode: {"python_code": code},
        WebhookTriggerNode: {"python_code": code, "node_name": "hook"},
    }.get(model, {})
    return model.objects.create(graph=graph, **extra, **flags)


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="grant-models", org=default_org)


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "slot"), CASES)
def test_a_row_starts_with_every_box_unticked(model, slot, graph):
    node = _create(model, graph)

    node.refresh_from_db()
    assert [getattr(node, name) for name in slot.flag_names] == [False] * len(slot.flag_names)


@pytest.mark.django_db
@pytest.mark.parametrize(("model", "slot"), CASES)
def test_ticked_boxes_are_stored_as_given(model, slot, graph):
    values = (True, False, True)[: len(slot.flag_names)]
    flags = dict(zip(slot.flag_names, values, strict=True))

    node = _create(model, graph, **flags)

    node.refresh_from_db()
    assert [getattr(node, name) for name in slot.flag_names] == list(values)


@pytest.mark.parametrize(
    "model", [AgentNode, TaskNode, FileExtractorNode, AudioTranscriptionNode]
)
def test_agent_task_and_file_nodes_have_no_grant(model):
    assert not [field.name for field in model._meta.fields if "storage_grant" in field.name]


@pytest.mark.django_db
def test_the_two_code_slots_of_a_classification_table_are_independent(graph):
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        pre_storage_grant_read=True,
        pre_storage_grant_write=True,
        pre_storage_grant_delete=True,
    )

    node.refresh_from_db()
    assert node.post_storage_grant_read is False


@pytest.mark.django_db
def test_a_session_may_hold_several_temporary_accounts(default_org):
    graph = Graph.objects.create(name="many-accounts", org=default_org)
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING)

    TemporaryStorageAccount.objects.create(session=session, access_key="first", shared_actions=["read"])
    TemporaryStorageAccount.objects.create(session=session, access_key="second", shared_actions=[])

    assert TemporaryStorageAccount.objects.filter(session=session).count() == 2


@pytest.mark.django_db
def test_an_account_still_has_exactly_one_owner(default_org):
    with pytest.raises(IntegrityError), transaction.atomic():
        TemporaryStorageAccount.objects.create(access_key="ownerless")


def test_every_grant_model_is_listed_for_the_tests_above():
    assert set(STORAGE_GRANT_SLOTS) == {
        PythonNode,
        WebhookTriggerNode,
        ClassificationDecisionTableNode,
    }
