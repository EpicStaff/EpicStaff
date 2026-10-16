from abc import ABC, abstractmethod
from typing import ClassVar

from django.db.models import Model
from tables.services.trigger_spec import TriggerSpec


class TriggerTestRunStrategy(ABC):
    """Turns a designer-written payload into the start of a run at one trigger node type.

    A strategy mirrors what the node type's real inbound handler passes to
    `run_session`, so a test run behaves like a real delivery without the HTTP
    ingress. Adding a node type: subclass this, set `node_type` (the canvas node
    type string) and `node_model`, implement the two builders, override
    `validate_payload` if the payload has a node-dependent shape, then list the
    class in `registry.TEST_RUN_STRATEGIES`.
    """

    node_type: ClassVar[str]
    node_model: ClassVar[type[Model]]

    def validate_payload(self, node: Model, payload: dict) -> None:
        """Check `payload` against `node`; the default accepts any JSON object.

        Raises:
            InvalidTestRunPayloadError: The payload cannot drive this node.
        """

    @abstractmethod
    def build_variables(self, payload: dict) -> dict:
        """Return the run variables the node type's real handler would pass."""

    @abstractmethod
    def build_trigger(self, node: Model, payload: dict) -> TriggerSpec:
        """Return the trigger the node type's real handler would record."""
