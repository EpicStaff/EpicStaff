import pytest

from tables.models.graph_models import Graph, GraphOrganization  # noqa: E402
from tables.services.persistent_variables_service import (
    _MISSING,
    PersistentVariablesService,
)

svc = PersistentVariablesService()


def test_get_by_path_missing_returns_sentinel():
    assert svc.get_by_path({"a": {"b": 1}}, "a.x") is _MISSING
    assert svc.get_by_path({}, "a") is _MISSING


def test_get_by_path_explicit_null_is_not_missing():
    # a value that is explicitly None must be distinguishable from "absent"
    assert svc.get_by_path({"context": None}, "context") is None


def test_get_by_path_nested_value():
    assert svc.get_by_path({"a": {"b": {"c": 5}}}, "a.b.c") == 5


def test_deep_merge_recurses_and_payload_wins():
    base = {"a": {"x": 1, "y": 2}, "k": "base"}
    updates = {"a": {"y": 99, "z": 3}, "k": "override"}
    assert svc.deep_merge(base, updates) == {
        "a": {"x": 1, "y": 99, "z": 3},
        "k": "override",
    }


def test_deep_merge_does_not_mutate_base():
    base = {"a": {"x": 1}}
    svc.deep_merge(base, {"a": {"x": 2}})
    assert base == {"a": {"x": 1}}


def test_extract_org_paths_including_null_default():
    variables = {
        "variables": {"counter": 0, "context": None, "ignored": "no"},
        "persistent_variables": {"organization": ["counter", "context"], "user": []},
    }
    assert svc.extract(variables, "organization") == {"counter": 0, "context": None}


def test_extract_skips_genuinely_missing_path():
    variables = {
        "variables": {"counter": 0},
        "persistent_variables": {"organization": ["counter", "gone"], "user": []},
    }
    assert svc.extract(variables, "organization") == {"counter": 0}


def _make_graph(default_org, *, flag, org_stored=None):
    graph = Graph.objects.create(
        name="run-vars", org=default_org, enable_persistent_variables=flag
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables=org_stored or {})
    return graph


@pytest.mark.django_db
def test_build_run_variables_flag_off_passes_payload_through(default_org):
    graph = _make_graph(default_org, flag=False, org_stored={"counter": 1})
    result = svc.build_run_variables(graph, None, {"a": 1})
    assert result.variables == {"a": 1}
    assert result.graph_user is None


@pytest.mark.django_db
def test_build_run_variables_merges_org_below_payload(default_org):
    graph = _make_graph(
        default_org, flag=True, org_stored={"counter": 5, "nested": {"x": 1}}
    )
    # payload wins on conflicting paths, deep-merges siblings
    result = svc.build_run_variables(graph, None, {"counter": 9, "nested": {"y": 2}})
    assert result.variables == {"counter": 9, "nested": {"x": 1, "y": 2}}


@pytest.mark.django_db
def test_build_run_variables_superadmin_has_no_graph_user(default_org, superadmin_user):
    graph = _make_graph(default_org, flag=True, org_stored={"counter": 5})
    result = svc.build_run_variables(graph, superadmin_user, {})
    assert result.graph_user is None
    assert result.variables == {"counter": 5}


@pytest.mark.django_db
def test_build_run_variables_member_gets_graph_user(default_org, regular_user):
    graph = _make_graph(default_org, flag=True, org_stored={})
    result = svc.build_run_variables(graph, regular_user, {})
    assert result.graph_user is not None
    assert result.graph_user.graph_id == graph.id
    assert result.graph_user.organization_user.user_id == regular_user.id
