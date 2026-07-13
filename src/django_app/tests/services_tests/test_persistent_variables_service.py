import pytest
from rest_framework import serializers

from tables.models.graph_models import (
    Graph,
    GraphOrganization,
    StartNode,
)
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


def _graph_with_start(default_org, *, flag, org_paths, defaults, org_stored=None):
    graph = Graph.objects.create(
        name="persist", org=default_org, enable_persistent_variables=flag
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": defaults,
            "persistent_variables": {"organization": org_paths, "user": []},
        },
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables=org_stored or {})
    return graph


class _FakeSession:
    def __init__(self, graph):
        self.graph = graph


@pytest.mark.django_db
def test_persist_writes_back_declared_paths(default_org):
    graph = _graph_with_start(
        default_org, flag=True, org_paths=["counter"], defaults={"counter": 0}
    )
    svc.persist_session_results(_FakeSession(graph), {"counter": 42, "noise": 1})
    go = GraphOrganization.objects.get(graph=graph)
    assert go.persistent_variables == {"counter": 42}


@pytest.mark.django_db
def test_persist_repopulates_emptied_storage(default_org):
    # storage is empty but the path is declared -> the session repopulates it,
    # because iteration is driven by the config, not by existing keys.
    graph = _graph_with_start(
        default_org,
        flag=True,
        org_paths=["counter"],
        defaults={"counter": 0},
        org_stored={},
    )
    svc.persist_session_results(_FakeSession(graph), {"counter": 7})
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 7
    }


@pytest.mark.django_db
def test_persist_noop_when_flag_off(default_org):
    graph = _graph_with_start(
        default_org, flag=False, org_paths=["counter"], defaults={"counter": 0}
    )
    svc.persist_session_results(_FakeSession(graph), {"counter": 99})
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {}


@pytest.mark.django_db
def test_persist_swallows_errors(default_org):
    graph = _graph_with_start(
        default_org, flag=True, org_paths=["counter"], defaults={"counter": 0}
    )
    # passing a non-dict must not raise (session end must never fail here)
    svc.persist_session_results(_FakeSession(graph), None)


def _domain(org_paths, defaults):
    return {
        "variables": defaults,
        "persistent_variables": {"organization": org_paths, "user": []},
    }


@pytest.mark.django_db
def test_sync_seeds_newly_declared_path_and_sets_flag(default_org):
    graph = Graph.objects.create(name="sync1", org=default_org)
    GraphOrganization.objects.create(graph=graph)
    svc.sync_from_start_node(graph, {}, _domain(["counter"], {"counter": 0}))
    graph.refresh_from_db()
    assert graph.enable_persistent_variables is True
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 0
    }


@pytest.mark.django_db
def test_sync_preserves_remembered_value_of_still_declared_path(default_org):
    graph = Graph.objects.create(
        name="sync2", org=default_org, enable_persistent_variables=True
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={"counter": 5})
    # value-only Domain edit (default changed 0 -> 100), path still declared
    svc.sync_from_start_node(
        graph,
        _domain(["counter"], {"counter": 0}),
        _domain(["counter"], {"counter": 100}),
    )
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 5
    }


@pytest.mark.django_db
def test_sync_drops_removed_path_and_clears_flag(default_org):
    graph = Graph.objects.create(
        name="sync3", org=default_org, enable_persistent_variables=True
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={"counter": 5})
    svc.sync_from_start_node(
        graph, _domain(["counter"], {"counter": 0}), _domain([], {"counter": 0})
    )
    graph.refresh_from_db()
    assert graph.enable_persistent_variables is False
    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {}


def test_validate_accepts_null_default():
    svc.validate_start_node_variables(
        _domain(["context"], {"context": None})
    )  # no raise


def test_validate_rejects_missing_path():
    with pytest.raises(serializers.ValidationError):
        svc.validate_start_node_variables(_domain(["gone"], {"counter": 0}))


def test_validate_tolerates_absent_variables_key():
    svc.validate_start_node_variables(None)  # no raise
    svc.validate_start_node_variables({})  # no raise


@pytest.mark.django_db
def test_seed_for_copy_extracts_org_values_and_sets_flag(default_org):
    graph = Graph.objects.create(name="copy-target", org=default_org)
    go = svc.seed_for_copy(graph, _domain(["counter"], {"counter": 3}))
    graph.refresh_from_db()
    assert go.persistent_variables == {"counter": 3}
    assert graph.enable_persistent_variables is True


@pytest.mark.django_db
def test_seed_for_copy_empty_when_no_paths(default_org):
    graph = Graph.objects.create(name="copy-empty", org=default_org)
    go = svc.seed_for_copy(graph, _domain([], {"counter": 3}))
    graph.refresh_from_db()
    assert go.persistent_variables == {}
    assert graph.enable_persistent_variables is False
