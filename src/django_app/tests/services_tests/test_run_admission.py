"""Every run entry point asks run admission first, and a refusal starts nothing.

The registered checks are replaced by test checks (`run_admission_fixtures`), so these tests
never depend on a real check. Redis is mocked; the database, views and services are real.
"""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from loguru import logger

from agents.models import AgentDefinition
from rbac.models import OrganizationUser
from tables.models import Graph, PythonCode, PythonCodeResult, PythonNode, Session
from tables.models.graph_models import (
    GraphOrganizationUser,
    GraphStorageFile,
    ScheduleTriggerNode,
    StartNode,
    StorageFile,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models import RealtimeChannel
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tables.models.session_models import SessionPrincipal, SessionTrigger
from tables.models.webhook_models import WebhookTrigger
from tables.services.run_admission import (
    REFUSAL_LOG_SECONDS,
    RunKind,
    RunSubject,
    assert_run_admitted,
    log_trigger_refusal_once,
    register_run_admission_check,
    registered_run_admission_checks,
)
from tables.services.run_resources import ResourceRef, RunResourceCollector
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.trigger_spec import TriggerSpec
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.fixtures import _make_secret
from tests.services_tests.run_admission_fixtures import *  # noqa: F401,F403
from tests.services_tests.run_admission_fixtures import (
    REFUSAL_EXTRA,
    REFUSAL_MESSAGE,
    RecordingCheck,
    RefusedForTestError,
    RefusingCheck,
)
from tests.services_tests.session_trigger_creation_test import (
    _empty_session_data,
    _stub_publish,
)


@pytest.fixture
def logged_warnings():
    lines: list[str] = []
    sink_id = logger.add(
        lambda message: lines.append(message.record["message"]), level="WARNING", format="{message}"
    )
    yield lines
    logger.remove(sink_id)


def _refusal_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("Run refused:")]


def _assert_refusal_envelope(response) -> None:
    assert response.status_code == 409, response.content
    assert response.json() == {
        **REFUSAL_EXTRA,
        "status_code": 409,
        "code": "test_refused",
        "message": REFUSAL_MESSAGE,
    }


@pytest.fixture
def flow(default_org):
    graph = Graph.objects.create(name="admission-flow", org=default_org)
    StartNode.objects.create(graph=graph, variables={"variables": {}})
    return graph


# --- The seam ---------------------------------------------------------------------------


def test_with_no_checks_every_run_is_admitted(run_admission_checks):
    assert assert_run_admitted(RunSubject(RunKind.FLOW, 1, 1)) is None


def test_registering_a_check_class_again_keeps_the_first_check(run_admission_checks):
    first, second = RecordingCheck(), RecordingCheck()

    register_run_admission_check(first)
    register_run_admission_check(second)

    assert registered_run_admission_checks() == (first,)


def test_checks_run_in_registration_order_and_the_first_refusal_wins(run_admission_checks):
    class CheckAfterTheRefusal(RecordingCheck):
        pass

    admitting, refusing, after = RecordingCheck(), RefusingCheck(), CheckAfterTheRefusal()
    for check in (admitting, refusing, after):
        register_run_admission_check(check)
    subject = RunSubject(RunKind.CODE, 5, 7)

    with pytest.raises(RefusedForTestError):
        assert_run_admitted(subject)

    assert registered_run_admission_checks() == (admitting, refusing, after)
    assert admitting.subjects == [subject]
    assert refusing.subjects == [subject]
    assert after.subjects == []


def test_a_subject_reads_its_kind_and_ids_from_text():
    subject = RunSubject("code", "5", "7")

    assert subject == RunSubject(RunKind.CODE, 5, 7)
    assert (type(subject.kind), type(subject.subject_id), type(subject.organization_id)) == (
        RunKind,
        int,
        int,
    )


@pytest.mark.parametrize(
    "kind, subject_id, organization_id",
    [("no-such-kind", 5, 7), (RunKind.FLOW, None, 7), (RunKind.FLOW, 5, "seven")],
)
def test_a_subject_that_names_no_kind_or_id_cannot_be_created(kind, subject_id, organization_id):
    with pytest.raises((TypeError, ValueError)):
        RunSubject(kind, subject_id, organization_id)


@pytest.mark.django_db
def test_a_refused_trigger_is_logged_once_per_node_and_cause(logged_warnings):
    refusal = RefusedForTestError("cause-a")

    log_trigger_refusal_once(trigger="schedule", node_id=5, graph_id=7, error=refusal)
    log_trigger_refusal_once(trigger="schedule", node_id=5, graph_id=7, error=refusal)
    log_trigger_refusal_once(trigger="schedule", node_id=6, graph_id=7, error=refusal)
    log_trigger_refusal_once(
        trigger="schedule", node_id=5, graph_id=7, error=RefusedForTestError("cause-b")
    )
    log_trigger_refusal_once(trigger="webhook", node_id=5, graph_id=7, error=refusal)

    line = f"trigger node 5 of flow 7: {REFUSAL_MESSAGE} (test_refused)"
    assert _refusal_lines(logged_warnings) == [
        f"Run refused: schedule {line}",
        f"Run refused: schedule {line.replace('node 5', 'node 6')}",
        f"Run refused: schedule {line}",
        f"Run refused: webhook {line}",
    ]


@pytest.mark.django_db
def test_a_refusal_is_remembered_for_a_day_and_logged_again_once_forgotten(logged_warnings):
    refusal = RefusedForTestError("cause")
    marker = "run_admission:refusal_logged:telegram:1:cause"

    log_trigger_refusal_once(trigger="telegram", node_id=1, graph_id=2, error=refusal)

    assert REFUSAL_LOG_SECONDS - 60 <= cache.ttl(marker) <= REFUSAL_LOG_SECONDS == 24 * 60 * 60
    cache.delete(marker)
    log_trigger_refusal_once(trigger="telegram", node_id=1, graph_id=2, error=refusal)
    assert len(_refusal_lines(logged_warnings)) == 2


# --- Flow runs: run_session covers every caller -----------------------------------------


@pytest.mark.django_db
def test_run_session_asks_admission_for_the_flow_in_its_organization(
    run_admission_checks, flow, regular_user, monkeypatch
):
    recording = RecordingCheck()
    run_admission_checks.append(recording)

    session_id = _stub_publish(monkeypatch).run_session(
        graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
    )

    assert Session.objects.filter(pk=session_id).exists()
    # Once before anything is written, and again just before the publish.
    assert recording.subjects == [RunSubject(RunKind.FLOW, flow.pk, flow.org_id)] * 2


@pytest.mark.django_db
def test_a_refused_run_session_writes_and_publishes_nothing(
    refusing_check, flow, regular_user, redis_client_mock
):
    with pytest.raises(RefusedForTestError):
        SessionManagerService().run_session(
            graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
        )

    assert not Session.objects.exists()
    assert not SessionTrigger.objects.exists()
    assert not SessionPrincipal.objects.exists()
    assert not GraphOrganizationUser.objects.filter(graph=flow).exists()
    redis_client_mock.publish.assert_not_called()
    assert refusing_check.subjects == [RunSubject(RunKind.FLOW, flow.pk, flow.org_id)]


@pytest.mark.django_db
def test_an_admitted_run_session_creates_the_rows_a_refusal_must_not(
    run_admission_checks, flow, regular_user, monkeypatch
):
    """The control for the test above: the same run, admitted, writes every row it checks."""
    session_id = _stub_publish(monkeypatch).run_session(
        graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
    )

    membership = OrganizationUser.objects.get(user=regular_user, org=flow.org)
    assert SessionTrigger.objects.filter(session_id=session_id).exists()
    assert SessionPrincipal.objects.filter(session_id=session_id).exists()
    assert GraphOrganizationUser.objects.filter(graph=flow, organization_user=membership).exists()


class RefusingFromTheSecondCheck(RecordingCheck):
    """Admits a run's first check and refuses the next, as a suspension in between would."""

    def check(self, subject: RunSubject) -> None:
        super().check(subject)
        if len(self.subjects) > 1:
            raise RefusedForTestError("suspended-meanwhile")


@pytest.fixture
def refused_before_the_publish(run_admission_checks):
    check = RefusingFromTheSecondCheck()
    run_admission_checks.append(check)
    yield check


@pytest.fixture
def built_and_published(monkeypatch):
    """Build no real session payload, and record what would be published and revoked."""
    session_manager = SessionManagerService()
    published, revoked = [], []
    monkeypatch.setattr(
        session_manager, "create_session_data", lambda session, **kwargs: _empty_session_data()
    )
    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        lambda **kwargs: published.append(kwargs) or 1,
    )
    from storage_credentials.services.session_credential_service import (
        session_credential_service,
    )

    monkeypatch.setattr(session_credential_service, "revoke_for_session", revoked.append)
    yield published, revoked


@pytest.mark.django_db
def test_a_run_refused_just_before_the_publish_is_stopped_and_never_published(
    refused_before_the_publish, built_and_published, flow, regular_user
):
    published, revoked = built_and_published

    with pytest.raises(RefusedForTestError):
        SessionManagerService().run_session(
            graph_id=flow.pk, variables={}, user=regular_user, trigger=TriggerSpec.manual()
        )

    session = Session.objects.get(graph=flow)
    assert session.status == Session.SessionStatus.STOP
    assert session.status_data == {"reason": REFUSAL_MESSAGE}
    assert session.finished_at is not None
    assert published == []
    assert revoked == [session.pk]
    assert refused_before_the_publish.subjects == [
        RunSubject(RunKind.FLOW, flow.pk, flow.org_id)
    ] * 2


@pytest.mark.django_db
def test_run_session_endpoint_answers_a_refusal_before_the_publish_with_the_same_409(
    refused_before_the_publish, built_and_published, flow, auth_client
):
    published, _ = built_and_published

    response = auth_client.post("/api/run-session/", {"graph_id": flow.pk}, format="json")

    _assert_refusal_envelope(response)
    assert published == []
    assert list(Session.objects.filter(graph=flow).values_list("status", flat=True)) == [
        Session.SessionStatus.STOP
    ]


@pytest.mark.django_db
def test_run_session_endpoint_answers_a_refusal_with_its_409_envelope(
    refusing_check, flow, auth_client, redis_client_mock
):
    response = auth_client.post("/api/run-session/", {"graph_id": flow.pk}, format="json")

    _assert_refusal_envelope(response)
    assert not Session.objects.exists()
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_trigger_test_run_endpoint_answers_a_refusal_with_409(
    refusing_check, flow, default_org, auth_client, redis_client_mock
):
    node = WebhookTriggerNode.objects.create(
        graph=flow,
        node_name="Incoming",
        webhook_trigger=WebhookTrigger.objects.create(path="admission-test-run", org=default_org),
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )

    response = auth_client.post(
        reverse("run-session-test"),
        {"graph_id": flow.pk, "node_type": "webhook-trigger", "node_id": node.pk, "payload": {}},
        format="json",
    )

    _assert_refusal_envelope(response)
    assert not Session.objects.exists()
    assert refusing_check.subjects == [RunSubject(RunKind.FLOW, flow.pk, default_org.pk)]


class RefusesRunsUsing:
    """Refuses a run whose collected resources include `refused`, as a suspension would."""

    def __init__(self, refused):
        self.refused = refused

    def check(self, subject: RunSubject) -> None:
        if self.refused in RunResourceCollector().collect(subject).refs:
            raise RefusedForTestError("uses-a-refused-row")


# --- Realtime and voice channels --------------------------------------------------------


@pytest.fixture
def voice_agent(default_org):
    agent_definition = AgentDefinition.objects.create(org=default_org, name="admission-voice")
    RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)
    return agent_definition


@pytest.mark.django_db
def test_realtime_init_answers_a_refusal_with_409_for_a_person(
    refusing_check, voice_agent, auth_client, redis_client_mock
):
    response = auth_client.post(
        "/api/init-realtime/", {"agent_definition_id": voice_agent.pk}, format="json"
    )

    _assert_refusal_envelope(response)
    assert not RealtimeAgentChat.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert refusing_check.subjects == [
        RunSubject(RunKind.REALTIME, voice_agent.pk, voice_agent.org_id)
    ]


@pytest.mark.django_db
def test_realtime_init_answers_a_refusal_with_409_for_the_voice_bridge(
    refusing_check, voice_agent, api_client, env_api_key, redis_client_mock
):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = api_client.post(
        "/api/init-realtime/", {"agent_definition_id": voice_agent.pk}, format="json"
    )

    _assert_refusal_envelope(response)
    assert not RealtimeAgentChat.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert refusing_check.subjects == [
        RunSubject(RunKind.REALTIME, voice_agent.pk, voice_agent.org_id)
    ]


@pytest.mark.django_db
def test_voice_channel_lookup_answers_a_refusal_with_409(
    refusing_check, default_org, api_client, env_api_key
):
    channel = RealtimeChannel.objects.create(name="admission-channel", org=default_org)
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = api_client.get(
        reverse("realtimechannel-lookup-by-token"), {"token": str(channel.token)}
    )

    _assert_refusal_envelope(response)
    assert refusing_check.subjects == [
        RunSubject(RunKind.VOICE_CHANNEL, channel.pk, default_org.pk)
    ]


@pytest.mark.django_db
def test_voice_channel_lookup_of_an_unknown_token_never_asks_admission(
    refusing_check, api_client, env_api_key
):
    raw_key, _ = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key)

    response = api_client.get(
        reverse("realtimechannel-lookup-by-token"),
        {"token": "00000000-0000-0000-0000-000000000000"},
    )

    assert response.status_code == 404
    assert refusing_check.subjects == []


@pytest.mark.django_db
def test_realtime_init_is_refused_when_the_agent_s_realtime_config_uses_a_refused_secret(
    run_admission_checks, default_org, auth_client, redis_client_mock
):
    refused = _make_secret(default_org, "admission-realtime-key", "sk-refused")
    agent = AgentDefinition.objects.create(org=default_org, name="admission-realtime")
    RealtimeAgentDefinition.objects.create(
        agent_definition=agent,
        openai_config=OpenAIRealtimeConfig.objects.create(
            custom_name="admission-openai", api_key_secret=refused, org=default_org
        ),
    )
    run_admission_checks.append(RefusesRunsUsing(ResourceRef("tables.Secret", refused.pk)))

    response = auth_client.post(
        "/api/init-realtime/", {"agent_definition_id": agent.pk}, format="json"
    )

    _assert_refusal_envelope(response)
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_a_refused_secret_named_in_the_realtime_config_override_is_never_used(
    run_admission_checks, default_org, auth_client, redis_client_mock
):
    refused = _make_secret(default_org, "admission-override-key", "sk-refused-override")
    agent = AgentDefinition.objects.create(org=default_org, name="admission-override")
    RealtimeAgentDefinition.objects.create(
        agent_definition=agent,
        openai_config=OpenAIRealtimeConfig.objects.create(
            custom_name="admission-own-openai",
            api_key_secret=_make_secret(default_org, "admission-own-key", "sk-own"),
            org=default_org,
        ),
    )
    run_admission_checks.append(RefusesRunsUsing(ResourceRef("tables.Secret", refused.pk)))

    response = auth_client.post(
        "/api/init-realtime/",
        {"agent_definition_id": agent.pk, "config": {"rt_api_key_secret_id": refused.pk}},
        format="json",
    )

    assert response.status_code == 201, response.content
    published = "".join(str(call) for call in redis_client_mock.publish.call_args_list)
    assert "sk-refused-override" not in published
    assert "sk-own" in published


# --- Code test runs ---------------------------------------------------------------------


@pytest.fixture
def python_node(flow):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonNode.objects.create(graph=flow, python_code=python_code, node_name="code")


@pytest.mark.django_db
def test_code_run_by_id_answers_a_refusal_with_409_and_writes_no_result(
    refusing_check, python_node, auth_client, redis_client_mock
):
    response = auth_client.post(
        "/api/run-python-code/",
        {"python_code_id": python_node.python_code_id, "variables": {}},
        format="json",
    )

    _assert_refusal_envelope(response)
    assert not PythonCodeResult.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert refusing_check.subjects == [
        RunSubject(RunKind.CODE, python_node.python_code_id, python_node.graph.org_id)
    ]


@pytest.mark.django_db
def test_code_run_of_a_target_answers_a_refusal_with_409_and_writes_no_result(
    refusing_check, python_node, auth_client, redis_client_mock
):
    response = auth_client.post(
        "/api/run-python-code/",
        {"target": {"type": "python_node", "id": python_node.pk}, "variables": {}},
        format="json",
    )

    _assert_refusal_envelope(response)
    assert not PythonCodeResult.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert refusing_check.subjects == [
        RunSubject(RunKind.CODE, python_node.python_code_id, python_node.graph.org_id)
    ]


@pytest.mark.django_db
@pytest.mark.parametrize("use_storage, expected_status", [(True, 409), (False, 200)])
def test_a_code_test_run_that_can_read_a_refused_attached_file_is_refused(
    run_admission_checks,
    flow,
    default_org,
    auth_client,
    redis_client_mock,
    use_storage,
    expected_status,
):
    attached = StorageFile.objects.create(org=default_org, name="input.csv", path="input.csv")
    GraphStorageFile.objects.create(graph=flow, storage_file=attached)
    code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    node = PythonNode.objects.create(graph=flow, python_code=code, use_storage=use_storage)
    run_admission_checks.append(RefusesRunsUsing(ResourceRef("tables.StorageFile", attached.pk)))

    response = auth_client.post(
        "/api/run-python-code/",
        {"target": {"type": "python_node", "id": node.pk}, "variables": {}},
        format="json",
    )

    assert response.status_code == expected_status, response.content
    assert PythonCodeResult.objects.exists() is (expected_status == 200)


# --- Triggers: refused quietly, logged once ---------------------------------------------


@pytest.fixture
def schedule_node(flow):
    return ScheduleTriggerNode.objects.create(
        graph=flow,
        node_name="every minute",
        is_active=True,
        next_run_date_time=timezone.now() + timedelta(minutes=1),
        current_runs=2,
    )


def _schedule_state(node: ScheduleTriggerNode) -> tuple:
    node.refresh_from_db()
    return node.current_runs, node.next_run_date_time, node.is_active, node.updated_at


@pytest.mark.django_db
def test_a_refused_schedule_tick_changes_nothing_and_logs_once(
    refusing_check, schedule_node, logged_warnings, redis_client_mock
):
    before = _schedule_state(schedule_node)
    redis_client_mock.reset_mock()

    ScheduleTriggerService().handle_schedule_trigger(schedule_node.pk)
    ScheduleTriggerService().handle_schedule_trigger(schedule_node.pk)

    assert _schedule_state(schedule_node) == before
    assert not Session.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert _refusal_lines(logged_warnings) == [
        f"Run refused: schedule trigger node {schedule_node.pk} of flow "
        f"{schedule_node.graph_id}: {REFUSAL_MESSAGE} (test_refused)"
    ]
    assert refusing_check.subjects == [
        RunSubject(RunKind.FLOW, schedule_node.graph_id, schedule_node.graph.org_id)
    ] * 2


@pytest.mark.django_db
def test_a_refused_schedule_logs_again_for_another_cause(
    run_admission_checks, schedule_node, logged_warnings
):
    run_admission_checks.append(RefusingCheck(log_key="first-cause"))
    ScheduleTriggerService().handle_schedule_trigger(schedule_node.pk)
    run_admission_checks[:] = [RefusingCheck(log_key="second-cause")]

    ScheduleTriggerService().handle_schedule_trigger(schedule_node.pk)

    assert len(_refusal_lines(logged_warnings)) == 2


@pytest.fixture
def two_flows_on_one_path(default_org):
    refused = Graph.objects.create(name="refused-flow", org=default_org)
    admitted = Graph.objects.create(name="admitted-flow", org=default_org)
    return refused, admitted


@pytest.mark.django_db
def test_a_refused_webhook_node_is_logged_once_and_the_other_node_still_runs(
    run_admission_checks, two_flows_on_one_path, default_org, logged_warnings, monkeypatch
):
    refused, admitted = two_flows_on_one_path
    trigger = WebhookTrigger.objects.create(path="admission-hook", org=default_org)
    refused_node = WebhookTriggerNode.objects.create(
        graph=refused,
        node_name="refused",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    WebhookTriggerNode.objects.create(
        graph=admitted,
        node_name="admitted",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    run_admission_checks.append(RefusingCheck(refuses=lambda subject: subject.subject_id == refused.pk))
    _stub_publish(monkeypatch)

    WebhookTriggerService().handle_webhook_trigger(path="admission-hook", payload={})
    WebhookTriggerService().handle_webhook_trigger(path="admission-hook", payload={})

    assert not Session.objects.filter(graph=refused).exists()
    assert Session.objects.filter(graph=admitted).count() == 2
    assert _refusal_lines(logged_warnings) == [
        f"Run refused: webhook trigger node {refused_node.pk} of flow {refused.pk}: "
        f"{REFUSAL_MESSAGE} (test_refused)"
    ]
    assert not [line for line in logged_warnings if "could not start graph" in line]


@pytest.mark.django_db
def test_a_refused_telegram_node_is_logged_once_and_the_other_node_still_runs(
    run_admission_checks,
    two_flows_on_one_path,
    default_org,
    logged_warnings,
    monkeypatch,
    mock_telegram_service,
):
    refused, admitted = two_flows_on_one_path
    trigger = WebhookTrigger.objects.create(path="admission-bot", org=default_org)
    refused_node = TelegramTriggerNode.objects.create(
        graph=refused, node_name="refused", webhook_trigger=trigger
    )
    TelegramTriggerNode.objects.create(graph=admitted, node_name="admitted", webhook_trigger=trigger)
    run_admission_checks.append(RefusingCheck(refuses=lambda subject: subject.subject_id == refused.pk))
    _stub_publish(monkeypatch)

    TelegramTriggerService().handle_telegram_trigger(path="admission-bot", payload={})
    TelegramTriggerService().handle_telegram_trigger(path="admission-bot", payload={})

    assert not Session.objects.filter(graph=refused).exists()
    assert Session.objects.filter(graph=admitted).count() == 2
    assert _refusal_lines(logged_warnings) == [
        f"Run refused: telegram trigger node {refused_node.pk} of flow {refused.pk}: "
        f"{REFUSAL_MESSAGE} (test_refused)"
    ]
    assert not [line for line in logged_warnings if "could not start graph" in line]
