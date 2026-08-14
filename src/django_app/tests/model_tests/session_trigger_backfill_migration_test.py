from importlib import import_module

import pytest
from django.apps import apps as django_apps

from tables.models.graph_models import (
    Graph,
    GraphOrganizationUser,
    ScheduleTriggerNode,
    WebhookTriggerNode,
)
from tables.models.rbac_models import OrganizationUser
from tables.models.python_models import PythonCode
from tables.models.session_models import Session, SessionTrigger
from tables.models.webhook_models import WebhookTrigger

backfill_migration = import_module("tables.migrations.0208_sessiontrigger_and_backfill")


@pytest.mark.django_db
def test_backfill_classifies_all_session_shapes(default_org, regular_user):
    graph = Graph.objects.create(name="backfill", org=default_org)

    schedule_node = ScheduleTriggerNode.objects.create(
        graph=graph, node_name="my_schedule"
    )
    webhook_trigger = WebhookTrigger.objects.create(path="wpath")
    python_code = PythonCode.objects.create(code="def main(): return None")
    webhook_node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="my_webhook",
        webhook_trigger=webhook_trigger,
        python_code=python_code,
    )
    deleted_node_id = schedule_node.id + 100_000  # id that matches nothing

    schedule_session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        entrypoint=f"my_schedule #{schedule_node.id}",
    )
    webhook_session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        entrypoint=f"my_webhook #{webhook_node.id}",
    )
    parent_session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.END, variables={}
    )
    child_session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        parent_session=parent_session,
    )
    membership = OrganizationUser.objects.get(user=regular_user, org=default_org)
    graph_user = GraphOrganizationUser.objects.create(
        graph=graph, organization_user=membership
    )
    manual_session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        graph_user=graph_user,
    )
    deleted_node_session = Session.objects.create(
        graph=graph,
        status=Session.SessionStatus.END,
        variables={},
        entrypoint=f"gone_node #{deleted_node_id}",
    )
    already_backfilled_session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.END, variables={}
    )
    SessionTrigger.objects.create(
        session=already_backfilled_session,
        trigger_type=SessionTrigger.TriggerType.MANUAL,
    )

    backfill_migration.backfill_session_triggers(django_apps, None)

    assert schedule_session.trigger.trigger_type == SessionTrigger.TriggerType.SCHEDULE
    assert schedule_session.trigger.schedule_trigger_node_id == schedule_node.id
    assert schedule_session.trigger.node_name == "my_schedule"

    assert webhook_session.trigger.trigger_type == SessionTrigger.TriggerType.WEBHOOK
    assert webhook_session.trigger.webhook_trigger_node_id == webhook_node.id
    assert webhook_session.trigger.node_name == "my_webhook"

    assert child_session.trigger.trigger_type == SessionTrigger.TriggerType.PARENT_FLOW
    assert child_session.trigger.triggered_by_session_id == parent_session.id

    assert manual_session.trigger.trigger_type == SessionTrigger.TriggerType.MANUAL
    assert manual_session.trigger.triggered_by_user_id == graph_user.id

    deleted_node_session.refresh_from_db()
    assert (
        deleted_node_session.trigger.trigger_type == SessionTrigger.TriggerType.MANUAL
    )
    assert deleted_node_session.trigger.node_name == "gone_node"
    assert deleted_node_session.trigger.schedule_trigger_node_id is None
    assert deleted_node_session.trigger.webhook_trigger_node_id is None
    assert deleted_node_session.trigger.telegram_trigger_node_id is None

    # not duplicated
    assert (
        SessionTrigger.objects.filter(session=already_backfilled_session).count() == 1
    )

    # parent_session itself has no parent/entrypoint, so it backfills as a
    # plain MANUAL run (no triggered_by_user, since graph_user was never set).
    parent_session.refresh_from_db()
    assert parent_session.trigger.trigger_type == SessionTrigger.TriggerType.MANUAL
    assert parent_session.trigger.triggered_by_user_id is None


def test_parse_entrypoint_splits_on_last_hash_and_requires_digit_suffix():
    parse = backfill_migration._parse_entrypoint

    assert parse("my node #42") == ("my node", 42)
    assert parse("name with #hash #7") == ("name with #hash", 7)
    assert parse("no id here") == ("no id here", None)
    assert parse("trailing hash #notdigits") == ("trailing hash #notdigits", None)
