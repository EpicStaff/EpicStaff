"""The run-resource walk covers every reference that can lead to a row a plugin owns.

A model *reaches a root* when it is an ownable root model, or when one of its forward FK,
O2O or M2M fields targets a model that reaches a root. The walk's models are the flow and
the start model of every kind of run, plus every model the rows reach from them. Then:

- every forward reference of a walk model that reaches a root is followed, is the link of a
  followed child, or is exempt with a reason. A parent link counts only for a model the walk
  reaches as a child alone: a row it also reaches by a forward reference did not arrive
  through its parent, so that link must be followed or exempt like any other field. An M2M
  with an explicit through model counts when the through model is followed as a child;
- every model outside the walk with a CASCADE FK or O2O to a walk model, or a plain M2M to
  one, is stopped with a reason;
- every row, exemption and stop names an existing model and field, every reason says
  something, every row is reached, nothing is both followed and exempt or stopped, and an
  exemption or stop that is no longer needed fails;
- a child the walk never queries (it leads nowhere further) is not ownable itself.
"""

from collections.abc import Iterable, Mapping

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from plugins.ownership.ownership_recorder import ownable_models
from tables.services.run_resources import (
    RUN_REFERENCE_EXEMPTIONS,
    RUN_REFERENCES,
    RUN_SECRET_MARKERS,
    RUN_START_MODELS,
    RUN_TRAVERSAL_STOPS,
    FollowChildren,
    FollowField,
    unqueried_child_references,
)

GRAPH = "tables.Graph"


def _forward_relations(model: type[models.Model]) -> list[models.Field]:
    return [
        field
        for field in model._meta.get_fields()
        if field.is_relation
        and not field.auto_created
        and field.related_model is not None
        and (field.many_to_one or field.one_to_one or field.many_to_many)
    ]


def _models_reaching_roots(ownable: frozenset[str]) -> frozenset[str]:
    reaching = set(ownable)
    every_model = apps.get_models()
    grew = True
    while grew:
        grew = False
        for model in every_model:
            label = model._meta.label
            if label in reaching:
                continue
            if any(
                field.related_model._meta.label in reaching for field in _forward_relations(model)
            ):
                reaching.add(label)
                grew = True
    return frozenset(reaching)


def _field(label: str, name: str) -> models.Field | None:
    try:
        return apps.get_model(label)._meta.get_field(name)
    except (LookupError, FieldDoesNotExist):
        return None


def _is_forward_relation(label: str, name: str) -> bool:
    return any(
        field.name == name for field in _forward_relations(apps.get_model(label))
    )


def _is_child_link(field) -> bool:
    """A link whose rows go with the row they point at: a CASCADE FK or O2O, or a plain M2M."""
    if field.many_to_many:
        return bool(field.remote_field.through._meta.auto_created)
    return field.concrete and field.remote_field.on_delete is models.CASCADE


def find_coverage_problems(
    references: Iterable[FollowField | FollowChildren],
    exemptions: Mapping[tuple[str, str], str],
    stops: Mapping[tuple[str, str], str],
    ownable: Iterable[str],
) -> list[str]:
    """Return every way the tables fail to cover what a run can reach; empty when covered."""
    references = tuple(references)
    ownable = frozenset(ownable)
    follow_fields = {(row.model, row.field) for row in references if isinstance(row, FollowField)}
    follow_children = {(row.child, row.fk) for row in references if isinstance(row, FollowChildren)}

    problems = _naming_problems(follow_fields, follow_children, exemptions, stops)
    if problems:
        # The checks below need every named field to exist.
        return problems
    for (model_label, field_name), reason in sorted({**exemptions, **stops}.items()):
        if not reason.strip():
            kind = "exemption" if (model_label, field_name) in exemptions else "stop"
            problems.append(f"{kind} {model_label}.{field_name} has no reason")
    for model_label, field_name in sorted(follow_fields & set(exemptions)):
        problems.append(f"{model_label}.{field_name} is both followed and exempt")
    for child_label, fk_name in sorted(follow_children & set(stops)):
        problems.append(f"{child_label}.{fk_name} is both followed and stopped")

    starts = {GRAPH, *RUN_START_MODELS.values()}
    walk_models = _walk_models(follow_fields, follow_children)
    for model_label, field_name in sorted(follow_fields):
        if model_label not in walk_models:
            problems.append(f"followed field {model_label}.{field_name} is never reached")
    for child_label, fk_name in sorted(follow_children):
        if _target_of(child_label, fk_name) not in walk_models:
            problems.append(f"followed child link {child_label}.{fk_name} is never reached")

    forward_targets = {_target_of(model_label, field) for model_label, field in follow_fields}
    reached_other_than_as_child = starts | forward_targets
    child_links: dict[str, set[str]] = {}
    for child_label, fk_name in follow_children:
        child_links.setdefault(child_label, set()).add(fk_name)

    reaching = _models_reaching_roots(ownable)
    needed_exemptions: set[tuple[str, str]] = set()
    for model_label in sorted(walk_models):
        for field in _forward_relations(apps.get_model(model_label)):
            if field.related_model._meta.label not in reaching:
                continue
            key = (model_label, field.name)
            if key in follow_fields:
                continue
            if (
                field.name in child_links.get(model_label, ())
                and model_label not in reached_other_than_as_child
            ):
                continue
            if field.many_to_many and not field.remote_field.through._meta.auto_created:
                through = field.remote_field.through._meta.label
                if field.m2m_field_name() in child_links.get(through, ()):
                    continue
            if key in exemptions:
                needed_exemptions.add(key)
                continue
            problems.append(
                f"unclassified reference {model_label}.{field.name} -> "
                f"{field.related_model._meta.label}"
            )

    needed_stops: set[tuple[str, str]] = set()
    for model in apps.get_models():
        model_label = model._meta.label
        if model_label in walk_models or model._meta.proxy:
            continue
        for field in _forward_relations(model):
            target = field.related_model._meta.label
            if target not in walk_models or not _is_child_link(field):
                continue
            key = (model_label, field.name)
            if key in stops:
                needed_stops.add(key)
                continue
            problems.append(f"unclassified child {model_label}.{field.name} -> {target}")

    for model_label, field_name in sorted(set(exemptions) - needed_exemptions):
        problems.append(f"exemption {model_label}.{field_name} is no longer needed")
    for model_label, field_name in sorted(set(stops) - needed_stops):
        problems.append(f"stop {model_label}.{field_name} is no longer needed")
    return problems


def _target_of(model_label: str, field_name: str) -> str:
    return _field(model_label, field_name).related_model._meta.label


def _walk_models(follow_fields, follow_children) -> set[str]:
    """The walk's models: the flow and every start model, then whatever the rows reach."""
    walk_models = {GRAPH, *RUN_START_MODELS.values()}
    grew = True
    while grew:
        grew = False
        for model_label, field_name in follow_fields:
            target = _target_of(model_label, field_name)
            if model_label in walk_models and target not in walk_models:
                walk_models.add(target)
                grew = True
        for child_label, fk_name in follow_children:
            if _target_of(child_label, fk_name) in walk_models and child_label not in walk_models:
                walk_models.add(child_label)
                grew = True
    return walk_models


def _naming_problems(follow_fields, follow_children, exemptions, stops) -> list[str]:
    problems = []
    for model_label, field_name in sorted(follow_fields):
        field = _field(model_label, field_name)
        if field is None or not _is_forward_relation(model_label, field_name):
            problems.append(f"followed field {model_label}.{field_name} is not a forward relation")
        elif field.many_to_many and not field.remote_field.through._meta.auto_created:
            problems.append(
                f"followed field {model_label}.{field_name} has an explicit through model; "
                "follow the through model as a child instead"
            )
    for child_label, fk_name in sorted(follow_children):
        field = _field(child_label, fk_name)
        if field is None or not (field.many_to_one or field.one_to_one) or not field.concrete:
            problems.append(f"followed child link {child_label}.{fk_name} is not an FK or O2O")
    for kind, table in (("exemption", exemptions), ("stop", stops)):
        for model_label, field_name in sorted(table):
            if _field(model_label, field_name) is None:
                problems.append(f"{kind} {model_label}.{field_name} names no such field")
    return problems


def _ownable_labels() -> frozenset[str]:
    return frozenset(model._meta.label for model in ownable_models())


def test_the_walk_covers_every_reference_that_can_reach_an_owned_row():
    problems = find_coverage_problems(
        RUN_REFERENCES, RUN_REFERENCE_EXEMPTIONS, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == []


def test_a_missing_followed_field_is_reported():
    references = [row for row in RUN_REFERENCES if row != FollowField("tables.PythonCode", "secrets")]

    problems = find_coverage_problems(
        references, RUN_REFERENCE_EXEMPTIONS, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert "unclassified reference tables.PythonCode.secrets -> tables.Secret" in problems


def test_a_missing_child_is_reported():
    references = [row for row in RUN_REFERENCES if row != FollowChildren("tables.TaskNode", "graph")]

    problems = find_coverage_problems(
        references, RUN_REFERENCE_EXEMPTIONS, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert "unclassified child tables.TaskNode.graph -> tables.Graph" in problems
    assert "followed field tables.TaskNode.agent_definition is never reached" in problems


def test_a_missing_exemption_is_reported():
    exemptions = {
        key: reason
        for key, reason in RUN_REFERENCE_EXEMPTIONS.items()
        if key != ("agents.Surface", "owner_agent")
    }

    problems = find_coverage_problems(
        RUN_REFERENCES, exemptions, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == ["unclassified reference agents.Surface.owner_agent -> agents.AgentDefinition"]


def test_a_missing_stop_is_reported():
    stops = {key: reason for key, reason in RUN_TRAVERSAL_STOPS.items() if key != ("tables.Session", "graph")}

    problems = find_coverage_problems(
        RUN_REFERENCES, RUN_REFERENCE_EXEMPTIONS, stops, _ownable_labels()
    )

    assert problems == ["unclassified child tables.Session.graph -> tables.Graph"]


def test_an_exemption_that_is_no_longer_needed_is_reported():
    exemptions = {**RUN_REFERENCE_EXEMPTIONS, ("tables.Graph", "labels"): "Labels."}

    problems = find_coverage_problems(
        RUN_REFERENCES, exemptions, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == ["exemption tables.Graph.labels is no longer needed"]


def test_a_stop_that_is_no_longer_needed_is_reported():
    stops = {**RUN_TRAVERSAL_STOPS, ("tables.TwilioChannel", "webhook_trigger"): "Shared tunnels."}

    problems = find_coverage_problems(
        RUN_REFERENCES, RUN_REFERENCE_EXEMPTIONS, stops, _ownable_labels()
    )

    assert problems == ["stop tables.TwilioChannel.webhook_trigger is no longer needed"]


def test_rows_exemptions_and_stops_must_name_existing_fields():
    references = [*RUN_REFERENCES, FollowField("tables.PythonNode", "no_such_field")]
    exemptions = {**RUN_REFERENCE_EXEMPTIONS, ("tables.NoSuchModel", "field"): "Gone."}
    stops = {**RUN_TRAVERSAL_STOPS, ("tables.Session", "no_such_fk"): "Gone."}

    problems = find_coverage_problems(references, exemptions, stops, _ownable_labels())

    assert problems == [
        "followed field tables.PythonNode.no_such_field is not a forward relation",
        "exemption tables.NoSuchModel.field names no such field",
        "stop tables.Session.no_such_fk names no such field",
    ]


def test_every_reason_must_say_something():
    exemptions = {**RUN_REFERENCE_EXEMPTIONS, ("agents.Surface", "owner_agent"): "  "}

    problems = find_coverage_problems(
        RUN_REFERENCES, exemptions, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == ["exemption agents.Surface.owner_agent has no reason"]


def test_a_reference_cannot_be_both_followed_and_exempt():
    exemptions = {**RUN_REFERENCE_EXEMPTIONS, ("tables.PythonCode", "secrets"): "Both."}

    problems = find_coverage_problems(
        RUN_REFERENCES, exemptions, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert "tables.PythonCode.secrets is both followed and exempt" in problems


def test_a_child_cannot_be_both_followed_and_stopped():
    stops = {**RUN_TRAVERSAL_STOPS, ("tables.TaskNode", "graph"): "Both."}

    problems = find_coverage_problems(
        RUN_REFERENCES, RUN_REFERENCE_EXEMPTIONS, stops, _ownable_labels()
    )

    assert "tables.TaskNode.graph is both followed and stopped" in problems


def test_an_explicit_through_model_is_followed_as_a_child_not_as_a_field():
    references = [*RUN_REFERENCES, FollowField("agents.AgentDefinition", "default_surface_list")]

    problems = find_coverage_problems(
        references, RUN_REFERENCE_EXEMPTIONS, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == [
        "followed field agents.AgentDefinition.default_surface_list has an explicit through "
        "model; follow the through model as a child instead"
    ]


def test_a_parent_link_does_not_cover_a_model_also_reached_by_a_forward_reference():
    # A voice channel reaches its realtime agent definition forward, so the definition's
    # link to its agent must be followed even though the definition is also a child of it.
    references = [
        row
        for row in RUN_REFERENCES
        if row != FollowField("tables.RealtimeAgentDefinition", "agent_definition")
    ]

    problems = find_coverage_problems(
        references, RUN_REFERENCE_EXEMPTIONS, RUN_TRAVERSAL_STOPS, _ownable_labels()
    )

    assert problems == [
        "unclassified reference tables.RealtimeAgentDefinition.agent_definition -> "
        "agents.AgentDefinition"
    ]


def test_a_child_the_walk_never_queries_is_not_ownable():
    ownable = _ownable_labels()

    unqueried_ownable = sorted(
        row.child for row in unqueried_child_references() if row.child in ownable
    )

    assert unqueried_ownable == []


# ---- header markers ----


def _walk_models_of(references) -> set[str]:
    return _walk_models(
        {(row.model, row.field) for row in references if isinstance(row, FollowField)},
        {(row.child, row.fk) for row in references if isinstance(row, FollowChildren)},
    )


def test_every_header_field_of_a_walk_model_has_its_markers_followed():
    # The resolver fills markers in every payload field whose name ends in `extra_headers`.
    walk_models = _walk_models_of(RUN_REFERENCES)
    header_fields = {
        (model._meta.label, field.name)
        for model in apps.get_models()
        if model._meta.label in walk_models
        for field in model._meta.concrete_fields
        if field.name.endswith("extra_headers")
    }

    assert header_fields == {(row.model, row.field) for row in RUN_SECRET_MARKERS}


def test_every_marker_row_is_a_json_field_of_a_row_that_belongs_to_an_organization():
    # A marker is looked up in the organization of the row holding it.
    wrong = [
        row
        for row in RUN_SECRET_MARKERS
        if _field(row.model, row.field) is None
        or _field(row.model, row.field).get_internal_type() != "JSONField"
        or _field(row.model, "org") is None
        or _field(row.model, "org").related_model._meta.label != "rbac.Organization"
    ]

    assert wrong == []
