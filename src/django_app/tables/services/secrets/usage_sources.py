"""Where a Secret can be referenced, declared once for both usage surfaces.

Two mechanisms sit behind one interface: a direct `*_secret` ForeignKey, and a
`get_secret("NAME")` literal inside a PythonCode row. Adding a seventh FK or a new
node type that carries Python is one entry in USAGE_SOURCES, and both
`secret_usage_service.counts()` and `.summary()` pick it up.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from tables.models import (
    EmbeddingConfig,
    LLMConfig,
    McpTool,
    PythonCodeTool,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    PythonNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.serializers.org_scoped_fields import org_visible_queryset
from tables.services.secrets.code_scanner import GET_SECRET_FUNC, scan_secret_names
from utils.graph_utils import resolve_node_names


CATEGORY_FLOWS = "flows"
CATEGORY_TOOLS = "tools"
CATEGORY_LLM_CONFIGS = "llm_configs"

#: Fixed emission order for `categories` in the detail payload.
CATEGORY_ORDER = (CATEGORY_FLOWS, CATEGORY_TOOLS, CATEGORY_LLM_CONFIGS)

NODE_TYPE_PYTHON = "python"
NODE_TYPE_WEBHOOK_TRIGGER = "webhook-trigger"
NODE_TYPE_CLASSIFICATION_TABLE = "classification-decision-table"
NODE_TYPE_TELEGRAM_TRIGGER = "telegram-trigger"
NODE_TYPE_EDGE = "edge"


@dataclass(frozen=True)
class UsageHit:
    """One place a secret is referenced."""

    secret_id: int
    category: str
    resource_id: int | None = None
    """The Graph, for flows. None for tools and configs, which are named only."""
    resource_name: str = ""
    """Flow name, or the tool / config display name."""
    node_name: str | None = None
    """Flows only."""
    node_type: str | None = None
    """Flows only — one of the NODE_TYPE_* values."""


class UsageSource(ABC):
    """One place the platform can reference a Secret."""

    @abstractmethod
    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        """Every reference this source can see inside one organization.

        `secret_names` maps name -> secret_id for the org, unambiguous because
        Secret has UniqueConstraint(org, name). FK sources match on the ids; code
        sources match on the names their scan returns.
        """


def _declared_ids(*, code: str, secret_names: dict[str, int]) -> list[int]:
    """Secret ids this code actually asks for, in first-seen order.

    Names the scanner finds but the org does not have are dropped: the name is a
    string literal in user code, so a typo must not invent a usage row.
    """
    return [
        secret_names[name]
        for name in scan_secret_names(code=code)
        if name in secret_names
    ]


def _plain_node_name(*, formatted: str | None, node_id: int | None) -> str | None:
    """Strip the " #<id>" that resolve_node_names() appends.

    That suffix is the platform's node identity format for logs and langgraph.
    Every other flow source here reports node_name verbatim, so stripping keeps one
    category from reading differently in the dialog.
    """
    if formatted is None or node_id is None:
        return None
    suffix = f" #{node_id}"
    return formatted[: -len(suffix)] if formatted.endswith(suffix) else formatted


class FkUsageSource(UsageSource):
    """A model holding a direct `*_secret` ForeignKey, reported by its own name."""

    def __init__(self, *, model, secret_field: str, category: str, name_field: str):
        self.model = model
        self.secret_field = secret_field
        self.category = category
        self.name_field = name_field

    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        # Filtered on the resource's org as well as the secret's: a row in another
        # org is invisible here even if it somehow points at this org's secret, so
        # usage never reports something the caller cannot see.
        rows = self.model.objects.filter(
            org_id=org_id,
            **{f"{self.secret_field}_id__in": set(secret_names.values())},
        ).values_list(f"{self.secret_field}_id", self.name_field)

        return [
            UsageHit(
                secret_id=secret_id,
                category=self.category,
                resource_name=name,
            )
            for secret_id, name in rows
        ]


class FlowFkUsageSource(UsageSource):
    """A graph node holding a direct `*_secret` ForeignKey.

    Reported under `flows` rather than as a standalone resource, because the
    dialog groups every in-flow reference beneath its flow.
    """

    def __init__(self, *, model, secret_field: str, node_type: str):
        self.model = model
        self.secret_field = secret_field
        self.node_type = node_type

    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        rows = self.model.objects.filter(
            graph__org_id=org_id,
            **{f"{self.secret_field}_id__in": set(secret_names.values())},
        ).values_list(f"{self.secret_field}_id", "graph_id", "graph__name", "node_name")

        return [
            UsageHit(
                secret_id=secret_id,
                category=CATEGORY_FLOWS,
                resource_id=graph_id,
                resource_name=graph_name,
                node_name=node_name,
                node_type=self.node_type,
            )
            for secret_id, graph_id, graph_name, node_name in rows
        ]


class FlowCodeUsageSource(UsageSource):
    """A graph node whose PythonCode may declare secrets via get_secret("NAME").

    The `code__contains` filter is a narrowing prefilter only: it cannot replace
    the AST pass, because `get_secret` inside a comment or an unrelated string
    literal matches the SQL but must not count. Its whole job is to avoid parsing
    rows that cannot possibly match.
    """

    def __init__(self, *, model, code_field: str, node_type: str):
        self.model = model
        self.code_field = code_field
        self.node_type = node_type

    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        rows = self.model.objects.filter(
            graph__org_id=org_id,
            **{f"{self.code_field}__code__contains": GET_SECRET_FUNC},
        ).values_list(
            f"{self.code_field}__code", "graph_id", "graph__name", "node_name"
        )

        hits: list[UsageHit] = []
        for code, graph_id, graph_name, node_name in rows:
            for secret_id in _declared_ids(code=code, secret_names=secret_names):
                hits.append(
                    UsageHit(
                        secret_id=secret_id,
                        category=CATEGORY_FLOWS,
                        resource_id=graph_id,
                        resource_name=graph_name,
                        node_name=node_name,
                        node_type=self.node_type,
                    )
                )
        return hits


class ToolCodeUsageSource(UsageSource):
    """PythonCodeTool — a hybrid resource, so built-ins (org=NULL) count too.

    A built-in tool calling get_secret("X") resolves the *querying* org's X at run
    time, so deleting X really would break that tool for this org. org_visible_q
    is the same rule the RBAC guide mandates for hybrid targets.
    """

    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        rows = (
            org_visible_queryset(model=PythonCodeTool, org_id=org_id)
            .filter(python_code__code__contains=GET_SECRET_FUNC)
            .values_list("python_code__code", "name")
        )

        hits: list[UsageHit] = []
        for code, name in rows:
            for secret_id in _declared_ids(code=code, secret_names=secret_names):
                hits.append(
                    UsageHit(
                        secret_id=secret_id,
                        category=CATEGORY_TOOLS,
                        resource_name=name,
                    )
                )
        return hits


class ConditionalEdgeUsageSource(UsageSource):
    """ConditionalEdge has no name of its own — only source_node_id.

    Its display name comes from the node it branches off, the same identity
    converter_service.convert_conditional_edge_to_pydantic uses via
    resolver(conditional_edge.source_node_id).
    """

    def collect(self, *, org_id: int, secret_names: dict[str, int]) -> list[UsageHit]:
        rows = list(
            ConditionalEdge.objects.filter(
                graph__org_id=org_id,
                python_code__code__contains=GET_SECRET_FUNC,
            ).values_list(
                "python_code__code",
                "graph_id",
                "graph__name",
                "source_node_id",
                "id",
            )
        )
        if not rows:
            return []

        # One batched cross-table resolution for every source node at once —
        # resolve_node_names issues a single UNION query plus one SELECT per
        # matching table, so this stays bounded however many edges match.
        formatted_names = resolve_node_names(
            ids=[source_node_id for _, _, _, source_node_id, _ in rows]
        )

        hits: list[UsageHit] = []
        for code, graph_id, graph_name, source_node_id, edge_id in rows:
            node_name = (
                _plain_node_name(
                    formatted=formatted_names.get(source_node_id),
                    node_id=source_node_id,
                )
                or f"Conditional edge #{edge_id}"
            )
            for secret_id in _declared_ids(code=code, secret_names=secret_names):
                hits.append(
                    UsageHit(
                        secret_id=secret_id,
                        category=CATEGORY_FLOWS,
                        resource_id=graph_id,
                        resource_name=graph_name,
                        node_name=node_name,
                        node_type=NODE_TYPE_EDGE,
                    )
                )
        return hits


USAGE_SOURCES: tuple[UsageSource, ...] = (
    # --- FK-declared: the secret is chosen by reference ---
    FkUsageSource(
        model=LLMConfig,
        secret_field="api_key_secret",
        category=CATEGORY_LLM_CONFIGS,
        name_field="custom_name",
    ),
    FkUsageSource(
        model=EmbeddingConfig,
        secret_field="api_key_secret",
        category=CATEGORY_LLM_CONFIGS,
        name_field="custom_name",
    ),
    FkUsageSource(
        model=RealtimeConfig,
        secret_field="api_key_secret",
        category=CATEGORY_LLM_CONFIGS,
        name_field="custom_name",
    ),
    FkUsageSource(
        model=RealtimeTranscriptionConfig,
        secret_field="api_key_secret",
        category=CATEGORY_LLM_CONFIGS,
        name_field="custom_name",
    ),
    FkUsageSource(
        model=McpTool,
        secret_field="auth_secret",
        category=CATEGORY_TOOLS,
        name_field="name",
    ),
    FlowFkUsageSource(
        model=TelegramTriggerNode,
        secret_field="telegram_bot_api_key_secret",
        node_type=NODE_TYPE_TELEGRAM_TRIGGER,
    ),
    # --- code-declared: the get_secret("NAME") literal IS the declaration ---
    FlowCodeUsageSource(
        model=PythonNode, code_field="python_code", node_type=NODE_TYPE_PYTHON
    ),
    FlowCodeUsageSource(
        model=WebhookTriggerNode,
        code_field="python_code",
        node_type=NODE_TYPE_WEBHOOK_TRIGGER,
    ),
    FlowCodeUsageSource(
        model=ClassificationDecisionTableNode,
        code_field="pre_python_code",
        node_type=NODE_TYPE_CLASSIFICATION_TABLE,
    ),
    FlowCodeUsageSource(
        model=ClassificationDecisionTableNode,
        code_field="post_python_code",
        node_type=NODE_TYPE_CLASSIFICATION_TABLE,
    ),
    ConditionalEdgeUsageSource(),
    ToolCodeUsageSource(),
)
