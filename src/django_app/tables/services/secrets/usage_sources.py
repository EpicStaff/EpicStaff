"""Where a Secret can be referenced, declared once for both usage surfaces.

Two mechanisms sit behind one shape: a direct `*_secret` ForeignKey, and a
`PythonCode.secrets` declaration. The differences between the twelve sites are all
data — which model, which ORM path reaches the secret, how the row reaches its org —
so they are dataclass fields rather than subclasses, the same way PythonCodeSite is
written in the sibling module.

The six declaration sites are *derived* from PYTHON_CODE_SITES rather than repeated
here, so a new Python-carrying model cannot appear in the allow-list validator while
staying invisible to the deletion dialog.
"""

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
        """(secret_id, resource_key) as a queryset, for the union in counts().

        Two columns, no names and no node resolution: everything counts() needs and
        nothing it does not. The key embeds the category, so UNION's own DISTINCT
        performs the whole dedup — see _key_expression.
        """
        return (
            self._scoped(org_id=org_id, secret_ids=secret_ids)
            .annotate(usage_key=self._key_expression())
            .values_list(self.secret_path, "usage_key")
        )

    def collect(self, *, org_id: int, secret_ids: set[int]) -> list[UsageHit]:
        """Every reference this source can see inside one organization, in full.

        This is the detail path, for summary(). counts() deliberately does not come
        through here — it uses count_pairs(), which is why the secrets list no longer
        pays for graph names and node-name resolution it never renders.
        """
        if self.category != CATEGORY_FLOWS:
            return self._named_hits(org_id=org_id, secret_ids=secret_ids)
        if self.name_field is None:
            return self._edge_hits(org_id=org_id, secret_ids=secret_ids)
        return self._node_hits(org_id=org_id, secret_ids=secret_ids)

    def _scoped(self, *, org_id: int, secret_ids: set[int]):
        """Rows of this source in this org that point at one of these secrets.

        Filtered on the resource's org as well as the secret's: a row in another org
        stays invisible here even if it somehow points at this org's secret, so usage
        never reports something the caller cannot see.
        """
        rows = (
            self.model.objects.filter(**{self.org_path: org_id})
            if self.org_path is not None
            else org_visible_queryset(model=self.model, org_id=org_id)
        )
        # order_by() cleared because a combined (UNION) query rejects ordered
        # operands, and count_pairs() feeds exactly that.
        return rows.filter(**{f"{self.secret_path}__in": secret_ids}).order_by()

    def _key_expression(self):
        """The text expression whose distinct values ARE the resources counted.

        A flow counts once however many of its nodes reference the secret, so flow
        keys are the graph. Everything else counts by display name, and the category
        prefix is what folds the four config models into one llm_configs namespace.
        """
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

    def _named_hits(self, *, org_id: int, secret_ids: set[int]) -> list[UsageHit]:
        """A standalone resource, reported by its own name."""
        rows = self._scoped(org_id=org_id, secret_ids=secret_ids).values_list(
            self.secret_path, self.name_field
        )
        return [
            UsageHit(
                secret_id=secret_id,
                category=self.category,
                resource_name=name,
            )
            for secret_id, name in rows
        ]

    def _node_hits(self, *, org_id: int, secret_ids: set[int]) -> list[UsageHit]:
        """A named graph node, reported under `flows` beneath its own flow."""
        rows = self._scoped(org_id=org_id, secret_ids=secret_ids).values_list(
            self.secret_path, "graph_id", "graph__name", self.name_field
        )
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

    def _edge_hits(self, *, org_id: int, secret_ids: set[int]) -> list[UsageHit]:
        """A ConditionalEdge, which has no name of its own — only source_node_id.

        Its display name comes from the node it branches off, the same identity
        converter_service.convert_conditional_edge_to_pydantic uses via
        resolver(conditional_edge.source_node_id). This is the one shape that needs a
        second query, which is why it is a branch rather than the common path.
        """
        rows = list(
            self._scoped(org_id=org_id, secret_ids=secret_ids).values_list(
                self.secret_path, "graph_id", "graph__name", "source_node_id", "id"
            )
        )
        if not rows:
            return []

        # One batched cross-table resolution for every source node at once —
        # resolve_node_names issues a single UNION query plus one SELECT per matching
        # table, so this stays bounded however many edges match.
        formatted_names = resolve_node_names(
            ids=[source_node_id for _, _, _, source_node_id, _ in rows]
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
                node_type=self.node_type,
            )
            for secret_id, graph_id, graph_name, source_node_id, edge_id in rows
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


def _from_python_code_site(*, site: PythonCodeSite) -> UsageSource:
    """A PythonCode declaration site, read as a usage source.

    Derived rather than re-declared. python_code_sites owns which models carry
    Python; a site missing from that tuple is a hole in the allow-list, and a site
    missing here would be a wrong number on the deletion dialog. Deriving makes the
    second failure impossible rather than merely documented.

    node_type is what distinguishes the two: a flow node has one, and PythonCodeTool
    (the only org-owned site) does not.
    """
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
