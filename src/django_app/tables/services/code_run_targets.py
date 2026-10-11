from collections.abc import Callable
from dataclasses import dataclass

from django.db.models import Model
from src.shared.models import PythonCodeData
from tables.models import PythonCode
from tables.models.graph_models import PythonNode, WebhookTriggerNode
from tables.services.converter_service import ConverterService


@dataclass(frozen=True)
class CodeRunTarget:
    """One code slot that test mode can run the way a real run would.

    A target is a slot, not a node: a node with two code slots (pre and post
    computation) is two targets over the same model, each naming its own
    `code_field`. Adding a target: write `build_payload` on top of the converter
    method the real run uses for that slot, then add an entry to
    `CODE_RUN_TARGETS`. The key is the public `target.type` of
    `POST /run-python-code/`.

    Attributes:
        model: Graph-owned model holding the slot; looked up through `graph__org_id`.
        code_field: The slot's `PythonCode` foreign key. It is the single source of
            the slot's code: the lookup requires it to be set, so an empty
            nullable slot is "not found", and the result row references it.
        build_payload: Builds the slot's `PythonCodeData` with the converter method
            a real run uses. The second argument is the test run's writable
            storage folder, which takes the place of the real run's
            `sessions/<id>/`.
    """

    model: type[Model]
    code_field: str
    build_payload: Callable[[Model, str], PythonCodeData]

    def find_in_org(self, target_id: int, org_id: int) -> Model | None:
        """Return the slot's owner if it is live, in `org_id` and its slot is set."""
        return (
            self.model.objects.filter(
                graph__org_id=org_id,
                pk=target_id,
                **{f"{self.code_field}__isnull": False},
            )
            .select_related(self.code_field)
            .first()
        )

    def python_code_of(self, owner: Model) -> PythonCode:
        return getattr(owner, self.code_field)


def storage_path_for_test_run(target_type: str, target_id: int) -> str:
    """Return the folder a test run of one target may write to, reused across runs."""
    return f"test-runs/{target_type}-{target_id}/"


def _build_python_node_payload(python_node: PythonNode, storage_path: str) -> PythonCodeData:
    return (
        ConverterService()
        .convert_python_node_to_pydantic(
            python_node=python_node,
            graph_id=python_node.graph_id,
            extra_storage_paths=[storage_path],
        )
        .python_code
    )


def _build_webhook_trigger_node_payload(
    webhook_trigger_node: WebhookTriggerNode, _storage_path: str
) -> PythonCodeData:
    # Real runs give webhook trigger code no storage, so test mode has none either.
    return (
        ConverterService()
        .convert_webhook_trigger_node_to_pydantic(webhook_trigger_node=webhook_trigger_node)
        .python_code
    )


CODE_RUN_TARGETS: dict[str, CodeRunTarget] = {
    "python_node": CodeRunTarget(
        model=PythonNode,
        code_field="python_code",
        build_payload=_build_python_node_payload,
    ),
    "webhook_trigger_node": CodeRunTarget(
        model=WebhookTriggerNode,
        code_field="python_code",
        build_payload=_build_webhook_trigger_node_payload,
    ),
}
