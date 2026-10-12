import pytest
from django.utils import timezone

from tables.exceptions import InvalidTestRunPayloadError
from tables.models import Graph, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode, TelegramTriggerNodeField
from tables.models.session_models import SessionTrigger
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.trigger_test_run.telegram_trigger_strategy import (
    TelegramTriggerTestRunStrategy,
)

NO_FIELDS_MESSAGE = (
    "This Telegram trigger has no fields selected; select fields before running a test."
)


@pytest.fixture
def telegram_node(default_org, mock_telegram_service):
    graph = Graph.objects.create(name="telegram-test-run-strategy", org=default_org)
    return TelegramTriggerNode.objects.create(graph=graph, node_name="Bot")


@pytest.fixture
def node_with_fields(telegram_node):
    for parent, field_name in (
        ("message", "text"),
        ("message", "chat"),
        ("callback_query", "data"),
    ):
        TelegramTriggerNodeField.objects.create(
            telegram_trigger_node=telegram_node,
            parent=parent,
            field_name=field_name,
            variable_path=f"variables.{field_name}",
        )
    return telegram_node


def _messages(node, payload) -> list[str]:
    with pytest.raises(InvalidTestRunPayloadError) as raised:
        TelegramTriggerTestRunStrategy().validate_payload(node, payload)
    return raised.value.detail["payload"]


@pytest.mark.django_db
class TestTelegramPayloadValidation:
    @pytest.mark.parametrize(
        "payload",
        [{}, {"message": {"text": "hi"}}, {"update_id": 1}, {"update_id": 1, "edited_message": {}}],
        ids=["empty", "unselected-field", "update-id-only", "update-id-and-unknown-parent"],
    )
    def test_node_without_selected_fields_rejects_every_payload(self, telegram_node, payload):
        assert _messages(telegram_node, payload) == [NO_FIELDS_MESSAGE]

    @pytest.mark.parametrize(
        "payload, expected_messages",
        [
            (
                {"edited_message": {"text": "x"}},
                ["'edited_message': not a field parent selected on this node"],
            ),
            ({"message": "not an object"}, ["'message' must be an object"]),
            ({"message": None}, ["'message' must be an object"]),
            ({"message": ["text"]}, ["'message' must be an object"]),
            (
                {"message": {"photo": []}},
                ["'message.photo': field not selected on this node"],
            ),
            (
                {"callback_query": {"text": "a field of another parent"}},
                ["'callback_query.text': field not selected on this node"],
            ),
        ],
        ids=[
            "unselected-parent",
            "string-parent",
            "null-parent",
            "list-parent",
            "unselected-field",
            "field-of-another-parent",
        ],
    )
    def test_rejects_keys_outside_the_selection(
        self, node_with_fields, payload, expected_messages
    ):
        assert _messages(node_with_fields, payload) == expected_messages

    def test_collects_every_error_in_one_raise(self, node_with_fields):
        payload = {
            "message": {"text": "ok", "photo": [], "sticker": {}},
            "edited_message": {},
            "callback_query": 7,
        }

        assert _messages(node_with_fields, payload) == [
            "'message.photo': field not selected on this node",
            "'message.sticker': field not selected on this node",
            "'edited_message': not a field parent selected on this node",
            "'callback_query' must be an object",
        ]

    @pytest.mark.parametrize(
        "payload",
        [
            {},
            {"message": {}},
            {"message": {"text": "hi"}},
            {"message": {"text": None, "chat": "values are never inspected"}},
            {"message": {"text": "hi", "chat": {"id": 1}}, "callback_query": {"data": "x"}},
        ],
        ids=["empty", "empty-parent", "omitted-fields", "any-values", "all-fields"],
    )
    def test_accepts_payloads_within_the_selection(self, node_with_fields, payload):
        TelegramTriggerTestRunStrategy().validate_payload(node_with_fields, payload)

    @pytest.mark.parametrize(
        "payload",
        [
            {"update_id": 1},
            {"update_id": 1, "message": {"text": "hi"}},
            {"update_id": "not-an-integer", "message": {"text": "hi"}},
            {"update_id": None},
            {"update_id": {"nested": ["values are never inspected"]}},
        ],
        ids=[
            "update-id-only",
            "update-id-with-picked-field",
            "string-update-id",
            "null-update-id",
            "object-update-id",
        ],
    )
    def test_accepts_the_update_envelope_key(self, node_with_fields, payload):
        TelegramTriggerTestRunStrategy().validate_payload(node_with_fields, payload)

    def test_update_envelope_key_does_not_hide_other_unknown_parents(self, node_with_fields):
        payload = {"update_id": 1, "edited_message": {"text": "x"}}

        assert _messages(node_with_fields, payload) == [
            "'edited_message': not a field parent selected on this node"
        ]

    def test_soft_deleted_field_is_not_selected(self, node_with_fields):
        TelegramTriggerNodeField.objects.filter(
            telegram_trigger_node=node_with_fields, field_name="chat"
        ).update(is_soft_deleted=True, soft_deleted_at=timezone.now())

        assert _messages(node_with_fields, {"message": {"chat": {"id": 1}}}) == [
            "'message.chat': field not selected on this node"
        ]

    def test_only_soft_deleted_fields_count_as_no_selection(self, telegram_node):
        TelegramTriggerNodeField.objects.create(
            telegram_trigger_node=telegram_node,
            parent="message",
            field_name="text",
            variable_path="variables.text",
            is_soft_deleted=True,
            soft_deleted_at=timezone.now(),
        )

        assert _messages(telegram_node, {}) == [NO_FIELDS_MESSAGE]


@pytest.mark.django_db
class TestTelegramRunInputs:
    def test_variables_match_the_real_handler_shape(self):
        payload = {"message": {"text": "hi"}}

        assert TelegramTriggerTestRunStrategy().build_variables(payload) == {
            "telegram_payload": payload
        }

    def test_variables_keep_the_update_envelope_key(self):
        payload = {"update_id": 1, "message": {"text": "hi"}}

        assert TelegramTriggerTestRunStrategy().build_variables(payload) == {
            "telegram_payload": {"update_id": 1, "message": {"text": "hi"}}
        }

    def test_trigger_is_a_telegram_trigger_for_the_node(self, node_with_fields):
        trigger = TelegramTriggerTestRunStrategy().build_trigger(
            node_with_fields, {"message": {"chat": {"id": 77}}}
        )

        assert trigger.trigger_type == SessionTrigger.TriggerType.TELEGRAM
        assert trigger.telegram_trigger_node_id == node_with_fields.id
        assert trigger.node_name == "Bot"
        assert trigger.extra == {"chat_id": 77}

    def test_run_inputs_match_what_the_real_inbound_handler_passes(
        self, default_org, node_with_fields, mocker
    ):
        # The strategy mirrors `handle_telegram_trigger`; renaming the run variable
        # or changing the trigger in only one of them must fail here.
        node_with_fields.webhook_trigger = WebhookTrigger.objects.create(
            path="telegram-strategy-handler-link", org=default_org
        )
        node_with_fields.save()
        telegram_trigger_service = TelegramTriggerService()
        run_session = mocker.patch.object(
            telegram_trigger_service.session_manager_service, "run_session"
        )
        payload = {"update_id": 5, "message": {"text": "hi", "chat": {"id": 77}}}
        strategy = TelegramTriggerTestRunStrategy()

        telegram_trigger_service.handle_telegram_trigger(
            path="telegram-strategy-handler-link", payload=payload
        )

        run_session.assert_called_once()
        handler_kwargs = run_session.call_args.kwargs
        assert handler_kwargs["graph_id"] == node_with_fields.graph_id
        assert handler_kwargs["variables"] == strategy.build_variables(payload)
        assert handler_kwargs["trigger"] == strategy.build_trigger(node_with_fields, payload)
