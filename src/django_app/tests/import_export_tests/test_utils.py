import pytest
from copy import deepcopy

from rest_framework.exceptions import ValidationError

from agents.models import Surface
from tables.import_export.serializers.mcp_tools import McpToolImportSerializer
from tables.import_export.strategies.python_tools import python_code_key
from tables.models import McpTool
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.utils import (
    compared_values,
    ensure_unique_identifier,
    create_filters,
    filter_by_name_or_renamed_copy,
    import_values,
    nest_owned_surface_entries,
)


@pytest.mark.django_db
class TestEnsureUniqueIdentifier:
    def test_no_collision(self):
        result = ensure_unique_identifier("MyAgent", ["Other"])
        assert result == "MyAgent"

    def test_simple_collision(self):
        result = ensure_unique_identifier("MyAgent", ["MyAgent"])
        assert result == "MyAgent #2"

    def test_numbered_collision(self):
        result = ensure_unique_identifier("MyAgent", ["MyAgent", "MyAgent #2"])
        assert result == "MyAgent #3"

    def test_numbered_name_does_not_collapse_to_free_base(self):
        """Even though 'MyAgent' is free, a numbered collision like 'MyAgent #5'
        never collapses back to the plain base name -- it still gets numbered."""
        result = ensure_unique_identifier("MyAgent #5", ["MyAgent #5"])
        assert result == "MyAgent #2"

    def test_gap_filling(self):
        result = ensure_unique_identifier(
            "MyAgent", ["MyAgent", "MyAgent #2", "MyAgent #4"]
        )
        assert result == "MyAgent #3"

    def test_empty_existing_names(self):
        result = ensure_unique_identifier("MyAgent", [])
        assert result == "MyAgent"


@pytest.mark.django_db
class TestCreateFilters:
    def test_all_values(self):
        filters, null_filters = create_filters({"role": "agent", "goal": "test"})
        assert filters == {"role": "agent", "goal": "test"}
        assert null_filters == {}

    def test_with_nulls(self):
        filters, null_filters = create_filters({"role": "agent", "llm_config": None})
        assert filters == {"role": "agent"}
        assert null_filters == {"llm_config__isnull": True}

    def test_all_nulls(self):
        filters, null_filters = create_filters({"a": None, "b": None})
        assert filters == {}
        assert null_filters == {"a__isnull": True, "b__isnull": True}

    def test_empty_dict(self):
        filters, null_filters = create_filters({})
        assert filters == {}
        assert null_filters == {}


class TestPythonCodeKey:
    def test_trailing_whitespace_and_padded_libraries_are_ignored(self):
        assert python_code_key("print('hi')\n\n", " requests ", "run") == (
            python_code_key("print('hi')", "requests", "run")
        )

    def test_leading_whitespace_in_code_counts(self):
        # The sandbox indents every line, so an indented first line is different code.
        assert python_code_key("  print('hi')", "", "main") != python_code_key(
            "print('hi')", "", "main"
        )

    def test_stored_blank_entrypoint_is_not_main(self):
        assert python_code_key("x", "", "") != python_code_key("x", "", "main")

    @pytest.mark.parametrize(
        "other",
        [
            ("print('bye')", "requests", "main"),
            ("print('hi')", "", "main"),
            ("print('hi')", "requests", "run"),
        ],
    )
    def test_any_compared_value_differing_differs(self, other):
        assert python_code_key("print('hi')", "requests", "main") != python_code_key(*other)


@pytest.mark.django_db
class TestComparedValues:
    def test_file_values_are_stored_as_the_serializer_would(self):
        values = compared_values(
            McpTool,
            McpToolImportSerializer,
            {"transport": "  https://example.com  ", "timeout": "30"},
            ("transport", "timeout", "init_timeout"),
        )

        assert values == {"transport": "https://example.com", "timeout": 30.0, "init_timeout": 10}

    def test_rejected_values_are_listed_by_field(self):
        with pytest.raises(ValidationError) as exc:
            import_values(
                McpToolImportSerializer,
                {"timeout": "abc", "tool_name": None, "transport": "ok"},
                ("transport", "tool_name", "timeout"),
            )

        assert set(exc.value.detail) == {"timeout", "tool_name"}


@pytest.mark.django_db
class TestFilterByNameOrRenamedCopy:
    @pytest.fixture
    def surfaces(self, default_org):
        names = ["Surf (beta) #3", "Surf (beta)", "Surf (beta)#2", "Surf (beta) #x", "Surf (beta)ing #2"]
        return {
            name: Surface.objects.create(organization=default_org, name=name) for name in names
        }

    def test_matches_exact_name_first_then_renamed_copies_newest_first(self, surfaces):
        result = filter_by_name_or_renamed_copy(Surface.objects.all(), "Surf (beta)")

        assert [surface.name for surface in result] == [
            "Surf (beta)",
            "Surf (beta)#2",
            "Surf (beta) #3",
        ]

    def test_numbered_export_name_matches_its_base_copies(self, surfaces):
        result = filter_by_name_or_renamed_copy(Surface.objects.all(), "Surf (beta)#2")

        assert [surface.name for surface in result] == ["Surf (beta)#2", "Surf (beta) #3"]

    def test_missing_name_matches_nothing(self, surfaces):
        assert not filter_by_name_or_renamed_copy(Surface.objects.all(), None).exists()


class TestNestOwnedSurfaceEntries:
    def _export_data(self):
        return {
            EntityType.SURFACE: [{"id": 1, "name": "owned"}, {"id": 2, "name": "shared"}],
            EntityType.AGENT_DEFINITION: [
                {"id": 10, "owned_surfaces": [1, 99], OWNED_SURFACE_ENTRIES_KEY: ["forged"]},
                {"id": 11, "owned_surfaces": [1]},
            ],
            "main_entity": EntityType.GRAPH,
        }

    def test_moves_owned_entries_under_first_owner(self):
        nested = nest_owned_surface_entries(self._export_data())

        assert nested[EntityType.SURFACE] == [{"id": 2, "name": "shared"}]
        first_agent, second_agent = nested[EntityType.AGENT_DEFINITION]
        # An id without a Surface entry (99) is dropped; a forged value is replaced.
        assert first_agent[OWNED_SURFACE_ENTRIES_KEY] == [{"id": 1, "name": "owned"}]
        assert second_agent[OWNED_SURFACE_ENTRIES_KEY] == []
        assert nested["main_entity"] == EntityType.GRAPH

    def test_does_not_modify_input(self):
        export_data = self._export_data()
        snapshot = deepcopy(export_data)

        nest_owned_surface_entries(export_data)

        assert export_data == snapshot

    def test_without_agents_returns_input_unchanged(self):
        export_data = {EntityType.SURFACE: [{"id": 1}], "main_entity": EntityType.SURFACE}

        assert nest_owned_surface_entries(export_data) is export_data

    def test_rejects_duplicate_agent_ids(self):
        export_data = self._export_data()
        export_data[EntityType.AGENT_DEFINITION][1]["id"] = 10

        with pytest.raises(ValidationError):
            nest_owned_surface_entries(export_data)
