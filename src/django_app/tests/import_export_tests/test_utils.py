import pytest
from types import SimpleNamespace

from tables.import_export.utils import (
    ensure_unique_identifier,
    create_filters,
    python_code_equal,
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
class TestPythonCodeEqual:
    def _make_instance(
        self, code="print('hi')", entrypoint="main", libraries="", global_kwargs=None
    ):
        return SimpleNamespace(
            code=code,
            entrypoint=entrypoint,
            libraries=libraries,
            global_kwargs=global_kwargs,
        )

    def test_matching(self):
        instance = self._make_instance(code="print('hi')\n", libraries="requests")
        data = {
            "code": "print('hi')\n",
            "entrypoint": "main",
            "libraries": "requests",
            "global_kwargs": None,
        }
        assert python_code_equal(instance, data) is True

    def test_different_code(self):
        instance = self._make_instance(code="print('hi')\n")
        data = {
            "code": "print('bye')\n",
            "entrypoint": "main",
            "libraries": "",
            "global_kwargs": None,
        }
        assert python_code_equal(instance, data) is False

    def test_trailing_whitespace_normalization(self):
        instance = self._make_instance(code="print('hi')  \n")
        data = {
            "code": "print('hi')\n",
            "entrypoint": "main",
            "libraries": "",
            "global_kwargs": None,
        }
        assert python_code_equal(instance, data) is True

    def test_different_entrypoint(self):
        instance = self._make_instance(code="x\n", entrypoint="main")
        data = {
            "code": "x\n",
            "entrypoint": "run",
            "libraries": "",
            "global_kwargs": None,
        }
        assert python_code_equal(instance, data) is False
