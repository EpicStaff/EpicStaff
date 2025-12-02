from tables.services.session_manager_service import SessionManagerService
from tables.models.graph_models import WebhookTriggerNode
from utils.singleton_meta import SingletonMeta


class WebhookTriggerService(metaclass=SingletonMeta):
    def __init__(self, session_manager_service: SessionManagerService):
        self.session_manager_service = session_manager_service

    def handle_webhook_trigger(self, path: str, payload: dict) -> None:
        webhook_trigger_node_list = WebhookTriggerNode.objects.filter(
            webhook_trigger__path=path
        )

        for webhook_trigger_node in webhook_trigger_node_list:
            self.session_manager_service.run_session(
                graph_id=webhook_trigger_node.graph.pk,
                variables={"trigger_payload": payload},
                entrypoint=webhook_trigger_node.node_name,
            )
