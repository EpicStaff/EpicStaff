from dataclasses import dataclass

from django.db.models import F, TextField, Value
from django.db.models.functions import Cast, Concat

from tables.models import (
    EmbeddingConfig,
    LLMConfig,
    McpTool,
    RealtimeConfig,
    RealtimeTranscriptionConfig,
)
from tables.models.graph_models import ConditionalEdge, TelegramTriggerNode
from tables.serializers.org_scoped_fields import org_visible_queryset

# Shared with the declaration validator so the two features cannot drift on which
# node types exist or what their wire values are.
from tables.services.secrets.python_code_sites import (
    PYTHON_CODE_SITES,
    PythonCodeSite,
)
from utils.graph_utils import resolve_node_names


CATEGORY_FLOWS = "flows"
CATEGORY_TOOLS = "tools"
CATEGORY_LLM_CONFIGS = "llm_configs"

#: Fixed emission order for `categories` in the detail payload.
CATEGORY_ORDER = (CATEGORY_FLOWS, CATEGORY_TOOLS, CATEGORY_LLM_CONFIGS)

#: Telegram is an FK site rather than a Python-code site, so it lives here rather
#: than in python_code_sites.
NODE_TYPE_TELEGRAM_TRIGGER = "telegram-trigger"

# The three column shapes the twelve sources fall into. Sources sharing a shape share
# a column list, so the detail path unions each group as-is instead of padding every
# branch out to one common shape with typed NULLs.
SHAPE_NAMED = "named"
SHAPE_NODE = "node"
SHAPE_EDGE = "edge"


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


@dataclass(frozen=True)
class UsageSource:
    """One place the platform can reference a Secret."""

    model: type
    secret_path: str
    """ORM path from `model` to the secret id — "api_key_secret_id" for an FK site,
    "python_code__secrets__id" for a declaration site."""
    category: str
    org_path: str | None
    """ORM path from `model` to the org id. None means a hybrid resource that must be
    scoped with org_visible_queryset instead: built-ins carry org=NULL, so an org_id
    filter would hide them."""
    name_field: str | None
    """Display name. None means the row has no name of its own — ConditionalEdge,
    which borrows the identity of the node it branches off."""
    node_type: str | None = None
    """A NODE_TYPE_* value for flow nodes; None for standalone resources."""

    def count_pairs(self, *, org_id: int, secret_ids: set[int]):
        """(secret_id, resource_key) as a queryset, for the union in counts()."""
        return (
            self._scoped(org_id=org_id, secret_ids=secret_ids)
            .annotate(usage_key=self._key_expression())
            .values_list(self.secret_path, "usage_key")
        )

    @property
    def detail_shape(self) -> str:
        """Which projection this source contributes to in the detail union."""
        if self.category != CATEGORY_FLOWS:
            return SHAPE_NAMED
        return SHAPE_EDGE if self.name_field is None else SHAPE_NODE

    def named_rows(self, *, org_id: int, secret_ids: set[int]):
        """(secret_id, category, name) for a standalone resource."""
        return (
            self._scoped(org_id=org_id, secret_ids=secret_ids)
            .annotate(
                usage_category=Value(self.category, output_field=TextField()),
                usage_name=Cast(self.name_field, output_field=TextField()),
            )
            .values_list(self.secret_path, "usage_category", "usage_name")
        )

    def node_rows(self, *, org_id: int, secret_ids: set[int]):
        """(secret_id, node_type, graph_id, graph_name, node_name) for a named node."""
        return (
            self._scoped(org_id=org_id, secret_ids=secret_ids)
            .annotate(
                usage_node_type=Value(self.node_type, output_field=TextField()),
                usage_graph_name=Cast("graph__name", output_field=TextField()),
                usage_node_name=Cast(self.name_field, output_field=TextField()),
            )
            .values_list(
                self.secret_path,
                "usage_node_type",
                "graph_id",
                "usage_graph_name",
                "usage_node_name",
            )
        )

    def edge_rows(self, *, org_id: int, secret_ids: set[int]):
        """(secret_id, node_type, graph_id, graph_name, source_node_id, edge_id)."""
        return (
            self._scoped(org_id=org_id, secret_ids=secret_ids)
            .annotate(usage_node_type=Value(self.node_type, output_field=TextField()))
            .values_list(
                self.secret_path,
                "usage_node_type",
                "graph_id",
                "graph__name",
                "source_node_id",
                "id",
            )
        )

    def _scoped(self, *, org_id: int, secret_ids: set[int]):
        """Rows of this source in this org that point at one of these secrets."""
        rows = (
            self.model.objects.filter(**{self.org_path: org_id})
            if self.org_path is not None
            else org_visible_queryset(model=self.model, org_id=org_id)
        )
        # order_by() cleared because a combined (UNION) query rejects ordered
        # operands, and count_pairs() feeds exactly that.
        return rows.filter(**{f"{self.secret_path}__in": secret_ids}).order_by()

    def _key_expression(self):
        """The text expression whose distinct values ARE the resources counted."""
        if self.category == CATEGORY_FLOWS:
            return Concat(
                Value(f"{CATEGORY_FLOWS}:"),
                Cast("graph_id", output_field=TextField()),
                output_field=TextField(),
            )
        return Concat(
            Value(f"{self.category}:"),
            F(self.name_field),
            output_field=TextField(),
        )


def hits_from_named_rows(*, rows) -> list[UsageHit]:
    """Standalone resources, reported by their own names."""
    return [
        UsageHit(secret_id=secret_id, category=category, resource_name=name)
        for secret_id, category, name in rows
    ]


def hits_from_node_rows(*, rows) -> list[UsageHit]:
    """Named graph nodes, reported under `flows` beneath their own flow."""
    return [
        UsageHit(
            secret_id=secret_id,
            category=CATEGORY_FLOWS,
            resource_id=graph_id,
            resource_name=graph_name,
            node_name=node_name,
            node_type=node_type,
        )
        for secret_id, node_type, graph_id, graph_name, node_name in rows
    ]


def hits_from_edge_rows(*, rows) -> list[UsageHit]:
    """Conditional edges, which have no name of their own — only source_node_id."""
    rows = list(rows)
    if not rows:
        return []

    # One batched cross-table resolution for every source node at once —
    # resolve_node_names issues a single UNION query plus one SELECT per matching
    # table, so this stays bounded however many edges match.
    formatted_names = resolve_node_names(
        ids=[source_node_id for _, _, _, _, source_node_id, _ in rows]
    )

    return [
        UsageHit(
            secret_id=secret_id,
            category=CATEGORY_FLOWS,
            resource_id=graph_id,
            resource_name=graph_name,
            node_name=(
                _plain_node_name(
                    formatted=formatted_names.get(source_node_id),
                    node_id=source_node_id,
                )
                or f"Conditional edge #{edge_id}"
            ),
            node_type=node_type,
        )
        for secret_id, node_type, graph_id, graph_name, source_node_id, edge_id in rows
    ]


#: Assembler per shape, so the service can group, union and assemble without a branch.
HITS_ASSEMBLERS = {
    SHAPE_NAMED: hits_from_named_rows,
    SHAPE_NODE: hits_from_node_rows,
    SHAPE_EDGE: hits_from_edge_rows,
}

#: Projection method name per shape, paired with the assembler above.
SHAPE_PROJECTIONS = {
    SHAPE_NAMED: "named_rows",
    SHAPE_NODE: "node_rows",
    SHAPE_EDGE: "edge_rows",
}


def _plain_node_name(*, formatted: str | None, node_id: int | None) -> str | None:
    """Strip the " #<id>" that resolve_node_names() appends."""
    if formatted is None or node_id is None:
        return None
    suffix = f" #{node_id}"
    return formatted[: -len(suffix)] if formatted.endswith(suffix) else formatted


def _from_python_code_site(*, site: PythonCodeSite) -> UsageSource:
    """A PythonCode declaration site, read as a usage source."""
    return UsageSource(
        model=site.model,
        secret_path=f"{site.code_field}__secrets__id",
        category=CATEGORY_FLOWS if site.node_type else CATEGORY_TOOLS,
        org_path=site.org_path,
        name_field=site.name_field,
        node_type=site.node_type,
    )


USAGE_SOURCES: tuple[UsageSource, ...] = (
    # --- FK-declared: the secret is chosen by reference ---
    UsageSource(
        model=LLMConfig,
        secret_path="api_key_secret_id",
        category=CATEGORY_LLM_CONFIGS,
        org_path="org_id",
        name_field="custom_name",
    ),
    UsageSource(
        model=EmbeddingConfig,
        secret_path="api_key_secret_id",
        category=CATEGORY_LLM_CONFIGS,
        org_path="org_id",
        name_field="custom_name",
    ),
    UsageSource(
        model=RealtimeConfig,
        secret_path="api_key_secret_id",
        category=CATEGORY_LLM_CONFIGS,
        org_path="org_id",
        name_field="custom_name",
    ),
    UsageSource(
        model=RealtimeTranscriptionConfig,
        secret_path="api_key_secret_id",
        category=CATEGORY_LLM_CONFIGS,
        org_path="org_id",
        name_field="custom_name",
    ),
    UsageSource(
        model=McpTool,
        secret_path="auth_secret_id",
        category=CATEGORY_TOOLS,
        org_path="org_id",
        name_field="name",
    ),
    UsageSource(
        model=TelegramTriggerNode,
        secret_path="telegram_bot_api_key_secret_id",
        category=CATEGORY_FLOWS,
        org_path="graph__org_id",
        name_field="node_name",
        node_type=NODE_TYPE_TELEGRAM_TRIGGER,
    ),
    # --- declaration-declared: PythonCode.secrets IS the allow-list ---
    *(_from_python_code_site(site=site) for site in PYTHON_CODE_SITES),
)

#: The ConditionalEdge source, for the tests that assert its name-borrowing branch.
#: Named here rather than indexed by position so reordering the registry cannot
#: silently retarget them.
CONDITIONAL_EDGE_SOURCE: UsageSource = next(
    source for source in USAGE_SOURCES if source.model is ConditionalEdge
)
