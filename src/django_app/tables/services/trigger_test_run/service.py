from django.db.models import Model
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ApiKey
from tables.models import User
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_test_run.base import TriggerTestRunStrategy


class SessionTestRunService:
    def __init__(self, session_manager_service: SessionManagerService):
        self.session_manager_service = session_manager_service

    def run(
        self,
        *,
        strategy: TriggerTestRunStrategy,
        node: Model,
        payload: dict,
        user: User | SystemServicePrincipal,
        api_key: ApiKey | None = None,
    ) -> int:
        """Start a session at `node` as if `payload` had been delivered to it.

        The session is flagged as a test run here rather than in the strategy, so
        no strategy can record an editor test as a real delivery. Everything else,
        persistent-variable write-back included, behaves like a regular run.

        Args:
            node: Already resolved in the caller's active organization.

        Returns:
            The id of the created session.

        Raises:
            InvalidTestRunPayloadError: The payload does not fit the node.
        """
        strategy.validate_payload(node, payload)
        return self.session_manager_service.run_session(
            node.graph_id,
            variables=strategy.build_variables(payload),
            trigger=strategy.build_trigger(node, payload).as_test_run(),
            user=user,
            api_key=api_key,
        )
