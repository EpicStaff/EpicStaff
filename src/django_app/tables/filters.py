# from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, F, IntegerField, OuterRef
from django.db.models.functions import Cast, Extract
from django_filters import rest_framework as filters
from rest_framework.filters import BaseFilterBackend, OrderingFilter

from tables.models import (
    GraphSessionMessage,
    Provider,  # SourceCollection,
)
from tables.models.embedding_models import EmbeddingModel
from tables.models.llm_models import LLMModel
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCodeTool
from tables.models.session_models import Session, SessionTrigger
from tables.models.webhook_models import WebhookTrigger


class CharInFilter(filters.BaseInFilter, filters.CharFilter):
    pass


class StrictBooleanField(forms.NullBooleanField):
    """NullBooleanField that rejects unrecognised values instead of cleaning them to None.

    The stock field (and django-filter's `BooleanFilter`) silently turns `?flag=garbage`
    into "no filter", which returns the unfiltered list as if the caller had asked for it.
    Accepts `true`/`1` and `false`/`0`, case-insensitive; an empty value means "not supplied".
    """

    default_error_messages = {"invalid": "Must be 'true' or 'false'."}

    def to_python(self, value):
        if value in self.empty_values:
            return None
        parsed = super().to_python(value.lower() if isinstance(value, str) else value)
        if parsed is None:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return parsed


class StrictBooleanFilter(filters.BooleanFilter):
    field_class = StrictBooleanField

    def __init__(self, *args, **kwargs):
        # The default BooleanWidget maps unknown strings to None before the field sees them.
        kwargs.setdefault("widget", forms.TextInput)
        super().__init__(*args, **kwargs)


class LabelFilterBackend(BaseFilterBackend):
    """
    Filters graphs by label_id (repeatable). Each label_id includes its full
    subtree of descendants. Multiple label_ids use OR logic.
    Example: ?label_id=1&label_id=3

    Use ?no_label=true to return only graphs with no labels assigned.
    """

    def filter_queryset(self, request, queryset, view):
        from tables.utils.helpers import get_label_descendant_ids

        no_label = request.query_params.get("no_label", "").lower() in ("true", "1")
        label_ids = request.query_params.getlist("label_id")

        if no_label:
            return queryset.filter(labels__isnull=True).distinct()

        if not label_ids:
            return queryset
        all_ids: set[int] = set()
        for lid in label_ids:
            all_ids |= get_label_descendant_ids(int(lid))
        return queryset.filter(labels__in=all_ids).distinct()

    def get_schema_operation_parameters(self, view):
        return [
            {
                "name": "label_id",
                "required": False,
                "in": "query",
                "description": (
                    "Filter by label ID (includes all descendants). "
                    "Repeat to filter by multiple labels (OR logic)."
                ),
                "schema": {"type": "integer"},
            },
            {
                "name": "no_label",
                "required": False,
                "in": "query",
                "description": "If true, return only graphs with no labels.",
                "schema": {"type": "boolean"},
            },
        ]


class KeyValueTableEntryOrderingFilter(OrderingFilter):
    """Order entries by `?ordering=` with a `session` alias and a stable tiebreak.

    `session` sorts by `updated_by_session_id`; entries no run wrote sort last in both
    directions. `key`, then `id` break ties so offset pages never shuffle. Unknown
    terms are dropped and fall back to the view's default, like the stock filter.
    """

    # Only aliased terms are nullable. The rest are NOT NULL and sort plainly, so
    # Postgres can still scan the (table_id, key) index backwards for `-key`.
    nullable_field_aliases = {"session": "updated_by_session_id"}

    def filter_queryset(self, request, queryset, view):
        expressions = []
        for term in self.get_ordering(request, queryset, view):
            field_name = self.nullable_field_aliases.get(term.removeprefix("-"))
            if field_name is None:
                expressions.append(term)
            elif term.startswith("-"):
                expressions.append(F(field_name).desc(nulls_last=True))
            else:
                expressions.append(F(field_name).asc(nulls_last=True))
        return queryset.order_by(*expressions, "key", "id")


class SessionFilter(filters.FilterSet):
    status = CharInFilter(field_name="status", lookup_expr="in")
    node_name = filters.CharFilter(
        field_name="graphsessionmessage__name", lookup_expr="exact", distinct=True
    )
    graph_name = CharInFilter(field_name="graph__name", lookup_expr="in")
    is_error_cause = filters.BooleanFilter(method="filter_by_error_cause")
    trigger_type = CharInFilter(field_name="trigger__trigger_type", lookup_expr="in")
    is_test_run = StrictBooleanFilter(method="filter_by_test_run")

    created_at = filters.DateTimeFromToRangeFilter(field_name="created_at")
    # duration filters
    duration_lt = filters.NumberFilter(method="filter_duration_lt")
    duration_gt = filters.NumberFilter(method="filter_duration_gt")
    duration_lte = filters.NumberFilter(method="filter_duration_lte")
    duration_gte = filters.NumberFilter(method="filter_duration_gte")

    class Meta:
        model = Session
        fields = [
            "graph_id",
            "graph_name",
            "status",
            "node_name",
            "trigger_type",
            "is_test_run",
        ]

    def _annotate_duration(self, queryset):
        """Calculate duration and cast it to integer type"""
        return queryset.annotate(
            duration=Cast(
                Extract(F("finished_at") - F("created_at"), "epoch"),
                output_field=IntegerField(),
            )
        )

    def filter_duration_lt(self, queryset, name, value):
        return self._annotate_duration(queryset).filter(
            finished_at__isnull=False, duration__lt=value
        )

    def filter_duration_gt(self, queryset, name, value):
        return self._annotate_duration(queryset).filter(
            finished_at__isnull=False, duration__gt=value
        )

    def filter_duration_lte(self, queryset, name, value):
        return self._annotate_duration(queryset).filter(
            finished_at__isnull=False, duration__lte=value
        )

    def filter_duration_gte(self, queryset, name, value):
        return self._annotate_duration(queryset).filter(
            finished_at__isnull=False, duration__gte=value
        )

    def filter_by_test_run(self, queryset, name, value):
        # An EXISTS pair keeps `false` the exact complement of `true`: a join-based
        # exclude() would have to reason about sessions with no trigger row and
        # extras without the key, both of which compare as NULL.
        test_run_triggers = SessionTrigger.objects.filter(
            session_id=OuterRef("pk"),
            **{f"extra__{SessionTrigger.TEST_RUN_EXTRA_KEY}": True},
        )
        if value:
            return queryset.filter(Exists(test_run_triggers))
        return queryset.filter(~Exists(test_run_triggers))

    def filter_by_error_cause(self, queryset, name, value):
        """Returns sessions that finished with error on specific node"""
        if not value:
            return queryset

        node_name = self.data.get("node_name")

        messages = GraphSessionMessage.objects.filter(
            session=OuterRef("pk"), message_data__message_type="error"
        )
        if node_name:
            messages = messages.filter(name=node_name)

        return queryset.filter(Exists(messages)).distinct()


# class CollectionFilter(filters.FilterSet):
#     collection_id = filters.CharFilter(field_name="collection_id", lookup_expr="exact")

#     class Meta:
#         model = SourceCollection
#         fields = ["collection_id"]


class ProviderFilter(filters.FilterSet):
    model_type = filters.CharFilter(method="filter_by_model_type")

    class Meta:
        model = Provider
        fields = ["name", "model_type"]

    def filter_by_model_type(self, queryset, name, value):
        mapping = {
            "llm": "llmmodel",
            "embedding": "embeddingmodel",
            "realtime": "realtimemodel",
            "transcription": "realtimetranscriptionmodel",
        }

        relation = mapping.get(value)
        if relation:
            return queryset.filter(**{f"{relation}__isnull": False}).distinct()

        return queryset


class BaseTagFilter(filters.FilterSet):
    tags = filters.CharFilter(method="filter_by_tags")

    def filter_by_tags(self, queryset, name, value):
        tag_names = [tag.strip() for tag in value.split(",") if tag.strip()]

        if not tag_names:
            return queryset

        return queryset.filter(tags__name__in=tag_names).distinct()


class LLMModelFilter(BaseTagFilter):
    class Meta:
        model = LLMModel

        fields = {
            "name": ["exact", "icontains"],
            "llm_provider": ["exact"],
            "predefined": ["exact"],
            "is_visible": ["exact"],
        }


class EmbeddingModelFilter(BaseTagFilter):
    class Meta:
        model = EmbeddingModel
        fields = {
            "name": ["exact", "icontains"],
            "embedding_provider": ["exact"],
            "predefined": ["exact"],
            "is_visible": ["exact"],
        }


class IsFavoriteFilterMixin(filters.FilterSet):
    """Filters on the `is_favorite` annotation added by the viewset's
    get_queryset() (Exists() against the per-user favorite table). Not a real
    column, so it can't go through plain `filterset_fields` — it needs the
    `method=` form, filtering the already-annotated queryset directly.

    Must itself subclass FilterSet (not a plain mixin) — django_filters'
    FilterSetMetaclass only inherits `declared_filters` from base classes
    that went through the metaclass themselves, so a plain mixin's declared
    Filter would be silently dropped when combined with FilterSet below.
    """

    is_favorite = filters.BooleanFilter(
        method="filter_is_favorite",
        help_text="Filter tools by whether the current user has favorited them.",
    )

    def filter_is_favorite(self, queryset, name, value):
        return queryset.filter(is_favorite=value)


class PythonCodeToolFilter(IsFavoriteFilterMixin, filters.FilterSet):
    class Meta:
        model = PythonCodeTool
        fields = ["name", "python_code"]


class McpToolFilter(IsFavoriteFilterMixin, filters.FilterSet):
    class Meta:
        model = McpTool
        fields = ["name", "tool_name"]


class WebhookTriggerFilter(filters.FilterSet):
    kind = filters.CharFilter(field_name="auth__kind")

    class Meta:
        model = WebhookTrigger
        fields = ["kind"]
