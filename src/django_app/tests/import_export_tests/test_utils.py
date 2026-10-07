import sys

import pytest
from copy import deepcopy

from rest_framework.exceptions import ValidationError

from agents.models import Surface
from tables.models import PythonCode
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.utils import (
    ensure_unique_identifier,
    create_filters,
    filter_by_name_or_renamed_copy,
    nest_owned_surface_entries,
    PYTHON_WHITESPACE,
    python_code_match_q,
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


@pytest.mark.django_db
class TestPythonCodeMatchQ:
    @pytest.fixture
    def stored_code(self, db):
        return PythonCode.objects.create(
            code="print('hi')  \n", entrypoint="main", libraries="requests", global_kwargs={}
        )

    def _matches(self, stored_code, **overrides) -> bool:
        data = {
            "code": "print('hi')\n",
            "entrypoint": "main",
            "libraries": "requests",
            "global_kwargs": {},
            **overrides,
        }
        return PythonCode.objects.filter(python_code_match_q(data), id=stored_code.id).exists()

    def test_matching_ignores_trailing_whitespace(self, stored_code):
        assert self._matches(stored_code)

    def test_trailing_unicode_whitespace_is_ignored_like_str_rstrip(self, stored_code):
        assert self._matches(stored_code, code="print('hi')" + chr(0x3000) + "\xa0\t")

    def test_different_code(self, stored_code):
        assert not self._matches(stored_code, code="print('bye')\n")

    def test_leading_whitespace_still_counts(self, stored_code):
        assert not self._matches(stored_code, code=" print('hi')\n")

    def test_different_entrypoint(self, stored_code):
        assert not self._matches(stored_code, entrypoint="run")

    def test_different_libraries(self, stored_code):
        assert not self._matches(stored_code, libraries="")

    def test_different_global_kwargs(self, stored_code):
        assert not self._matches(stored_code, global_kwargs={"timeout": 5})

    @pytest.mark.parametrize("code_data", [None, {}, {"code": None}, {"code": 5}])
    def test_data_without_text_code_matches_nothing(self, code_data):
        assert python_code_match_q(code_data) is None

    def test_whitespace_set_is_what_str_rstrip_strips(self):
        assert set(PYTHON_WHITESPACE) == {
            chr(code_point)
            for code_point in range(sys.maxunicode + 1)
            if chr(code_point).isspace()
        }


@pytest.mark.django_db
class TestFilterByNameOrRenamedCopy:
    @pytest.fixture
    def surfaces(self, default_org):
        names = ["Surf (beta) #3", "Surf (beta)", "Surf (beta)#2", "Surf (beta) #x", "Surf (beta)ing #2"]
        return {
            name: Surface.objects.create(organization=default_org, name=name) for name in names
        }

    def test_matches_exact_name_and_renamed_copies_exact_first(self, surfaces):
        result = filter_by_name_or_renamed_copy(Surface.objects.all(), "Surf (beta)")

        assert [surface.name for surface in result] == [
            "Surf (beta)",
            "Surf (beta) #3",
            "Surf (beta)#2",
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
