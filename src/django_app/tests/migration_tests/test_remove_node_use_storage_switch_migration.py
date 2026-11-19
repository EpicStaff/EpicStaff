"""tables 0294 and 0295 remove the storage switch of Python, Webhook trigger and Classification decision table nodes.

Invariants: a node whose switch was off had no storage, but migration 0287 ticked its boxes,
so the migration unticks them before the switch is dropped and removing the switch grants
nothing. A node whose switch was on keeps its boxes. Going back restores the switch of every
slot that has a box ticked.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

BEFORE = ("tables", "0293_merge_20261116_1030")
AFTER = ("tables", "0295_remove_node_use_storage_switch")

BOXES = ("storage_grant_read", "storage_grant_write", "storage_grant_delete")


def _migrate(target):
    MigrationExecutor(connection).migrate([target])
    return MigrationExecutor(connection).loader.project_state([target]).apps


def _boxes(node, prefix=""):
    return tuple(getattr(node, f"{prefix}{box}") for box in BOXES)


def _ticked(prefix=""):
    return {f"{prefix}{box}": True for box in BOXES}


@pytest.fixture
def restore_latest_schema():
    yield
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())


@pytest.fixture
def before_apps(restore_latest_schema):
    return _migrate(BEFORE)


@pytest.fixture
def nodes_before(before_apps):
    """Nodes as 0287 left them: every box ticked, whatever the switch says."""
    organization = before_apps.get_model("rbac", "Organization").objects.create(name="switch-removal")
    graph = before_apps.get_model("tables", "Graph").objects.create(name="g", org=organization)
    code_model = before_apps.get_model("tables", "PythonCode")

    def code():
        return code_model.objects.create(code="x", entrypoint="main")

    python_model = before_apps.get_model("tables", "PythonNode")
    webhook_model = before_apps.get_model("tables", "WebhookTriggerNode")
    cdt_model = before_apps.get_model("tables", "ClassificationDecisionTableNode")
    return {
        "python_off": python_model.objects.create(
            graph=graph, python_code=code(), use_storage=False, **_ticked()
        ).pk,
        "python_on": python_model.objects.create(
            graph=graph, python_code=code(), use_storage=True, **_ticked()
        ).pk,
        "webhook_off": webhook_model.objects.create(
            graph=graph, node_name="off", python_code=code(), use_storage=False, **_ticked()
        ).pk,
        "webhook_on": webhook_model.objects.create(
            graph=graph, node_name="on", python_code=code(), use_storage=True, **_ticked()
        ).pk,
        "cdt_post_only": cdt_model.objects.create(
            graph=graph,
            node_name="post-only",
            pre_use_storage=False,
            post_use_storage=True,
            **_ticked("pre_"),
            **_ticked("post_"),
        ).pk,
    }


@pytest.mark.django_db(transaction=True)
def test_a_node_whose_switch_was_off_ends_up_with_no_box_ticked(nodes_before):
    after_apps = _migrate(AFTER)

    def stored(model_name, key):
        return after_apps.get_model("tables", model_name).objects.get(pk=nodes_before[key])

    assert _boxes(stored("PythonNode", "python_off")) == (False, False, False)
    assert _boxes(stored("WebhookTriggerNode", "webhook_off")) == (False, False, False)


@pytest.mark.django_db(transaction=True)
def test_a_node_whose_switch_was_on_keeps_its_boxes(nodes_before):
    after_apps = _migrate(AFTER)

    def stored(model_name, key):
        return after_apps.get_model("tables", model_name).objects.get(pk=nodes_before[key])

    assert _boxes(stored("PythonNode", "python_on")) == (True, True, True)
    assert _boxes(stored("WebhookTriggerNode", "webhook_on")) == (True, True, True)


@pytest.mark.django_db(transaction=True)
def test_each_code_slot_of_a_classification_table_follows_its_own_switch(nodes_before):
    after_apps = _migrate(AFTER)

    node = after_apps.get_model("tables", "ClassificationDecisionTableNode").objects.get(
        pk=nodes_before["cdt_post_only"]
    )

    assert _boxes(node, "pre_") == (False, False, False)
    assert _boxes(node, "post_") == (True, True, True)


@pytest.mark.django_db(transaction=True)
def test_the_switch_columns_are_gone(nodes_before):
    after_apps = _migrate(AFTER)

    for model_name, switches in (
        ("PythonNode", {"use_storage"}),
        ("WebhookTriggerNode", {"use_storage"}),
        ("ClassificationDecisionTableNode", {"pre_use_storage", "post_use_storage"}),
    ):
        field_names = {field.name for field in after_apps.get_model("tables", model_name)._meta.fields}
        assert not field_names & switches


@pytest.mark.django_db(transaction=True)
def test_going_back_switches_on_every_slot_with_a_box_ticked(nodes_before):
    _migrate(AFTER)
    after_apps = MigrationExecutor(connection).loader.project_state([AFTER]).apps
    after_apps.get_model("tables", "PythonNode").objects.filter(pk=nodes_before["python_on"]).update(
        storage_grant_delete=False
    )

    old_apps = _migrate(BEFORE)

    def stored(model_name, key):
        return old_apps.get_model("tables", model_name).objects.get(pk=nodes_before[key])

    assert stored("PythonNode", "python_on").use_storage is True
    assert stored("PythonNode", "python_off").use_storage is False
    assert stored("WebhookTriggerNode", "webhook_on").use_storage is True
    assert stored("WebhookTriggerNode", "webhook_off").use_storage is False
    cdt = stored("ClassificationDecisionTableNode", "cdt_post_only")
    assert (cdt.pre_use_storage, cdt.post_use_storage) == (False, True)
