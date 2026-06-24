"""Layer 3 tests: GraphVersioningService."""

import pytest

from tables.import_export.constants import IMPORT_VERSION
from tables.import_export.enums import EntityType
from tables.models import GraphVersion
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Group A: save_version — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_save_version_creates_graph_version_row(service, graph):
    version = service.save_version(graph, name="v1", description="first save")

    assert GraphVersion.objects.filter(id=version.id).exists()
    assert version.graph_id == graph.id
    assert version.name == "v1"
    assert version.description == "first save"


@pytest.mark.django_db
def test_save_version_snapshot_contains_version_field(service, graph):
    version = service.save_version(graph, name="v1")

    assert version.snapshot["version"] == IMPORT_VERSION


@pytest.mark.django_db
def test_save_version_records_dependencies_for_crew_node(service, graph, crew):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)

    version = service.save_version(graph, name="with-crew")

    assert EntityType.CREW.value in version.dependencies
    assert crew.id in version.dependencies[EntityType.CREW.value]


@pytest.mark.django_db
def test_save_version_default_description_is_empty(service, graph):
    version = service.save_version(graph, name="no-desc")

    assert version.description == ""


# ---------------------------------------------------------------------------
# Group B: restore_version happy path — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_version_returns_response_dict_structure(service, graph):
    version = service.save_version(graph, name="snap")

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    assert result["restored"] is True
    assert result["graph_id"] == graph.id
    assert isinstance(result["warnings"], list)
    assert result["auto_backup_version_id"] is None


@pytest.mark.django_db
def test_restore_version_round_trip_restores_crew_node(service, graph, crew):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    version = service.save_version(graph, name="snap-with-crew")

    # Wipe the node so the graph is empty before restore
    graph.crew_node_list.all().delete()
    assert graph.crew_node_list.count() == 0

    service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    assert graph.crew_node_list.count() == 1
    restored_node = graph.crew_node_list.first()
    assert restored_node.crew_id == crew.id


# ---------------------------------------------------------------------------
# Group C: restore_version with missing dependencies — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_version_with_missing_crew_returns_warnings_and_skips_node(
    service, graph, crew
):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    # Save snapshot while crew still exists — dependencies are recorded
    version = service.save_version(graph, name="snap-crew-present")

    # Deleting the crew also cascade-deletes the CrewNode (FK CASCADE),
    # so the graph is already empty. The snapshot still references the old
    # crew id, so validate_dependencies puts it in "missing", and
    # filter_snapshot skips the node during restore.
    crew.delete()

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    assert len(result["warnings"]) > 0
    skipped = [w for w in result["warnings"] if w["type"] == "node_skipped"]
    assert len(skipped) > 0
    assert graph.crew_node_list.count() == 0


# ---------------------------------------------------------------------------
# Group D: backup flag — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_version_with_backup_true_creates_backup_version(service, graph):
    version = service.save_version(graph, name="original")
    before_count = GraphVersion.objects.count()

    result = service.restore_version(
        version, backup=True, expected_save_version=graph.save_version
    )

    assert result["auto_backup_version_id"] is not None
    assert GraphVersion.objects.count() == before_count + 1
    backup = GraphVersion.objects.get(id=result["auto_backup_version_id"])
    assert backup.name.startswith("Before restore to '")


@pytest.mark.django_db
def test_restore_version_with_backup_false_creates_no_backup(service, graph):
    version = service.save_version(graph, name="original")
    before_count = GraphVersion.objects.count()

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    assert GraphVersion.objects.count() == before_count
    assert result["auto_backup_version_id"] is None


# ---------------------------------------------------------------------------
# Group E: warnings ID remap — DB integration test
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_restore_version_warnings_node_ids_are_remapped_to_new_ids(
    service, graph, llm_config
):
    from tables.models import CodeAgentNode

    # Create a CodeAgentNode that references an LLMConfig (NullFK handler).
    # When llm_config is deleted, restore will emit a fk_nulled warning whose
    # node_id must reference the *new* DB id assigned during restore, not the
    # old snapshot id.
    node = CodeAgentNode.objects.create(
        graph=graph,
        node_name="ca",
        llm_config=llm_config,
    )
    old_snapshot_id = node.id

    version = service.save_version(graph, name="snap-with-code-agent")

    # Delete the LLMConfig — node is kept but FK will be nulled on restore
    llm_config.delete()

    result = service.restore_version(
        version, backup=False, expected_save_version=graph.save_version
    )

    fk_nulled_warnings = [w for w in result["warnings"] if w["type"] == "fk_nulled"]
    assert len(fk_nulled_warnings) > 0

    # After restore the CodeAgentNode is recreated with a brand-new DB id.
    # change_old_warnings_ids must have updated node_id to point to the new row.
    new_node = graph.code_agent_node_list.first()
    assert new_node is not None
    assert fk_nulled_warnings[0]["node_id"] == new_node.id
    # Sanity-check: the new id differs from the old snapshot id (it was remapped)
    assert fk_nulled_warnings[0]["node_id"] != old_snapshot_id


# ---------------------------------------------------------------------------
# Group F: create_graph_from_version — DB tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_graph_from_version_creates_new_graph_row(service, graph, default_org):
    version = service.save_version(graph, name="my-version")

    result = service.create_graph_from_version(version)

    assert result["created"] is True
    new_graph_id = result["graph_id"]
    assert new_graph_id != graph.id
    assert Graph.objects.filter(id=new_graph_id).exists()


@pytest.mark.django_db
def test_create_graph_from_version_uses_version_name(service, graph, default_org):
    version = service.save_version(graph, name="my-snapshot-name")

    result = service.create_graph_from_version(version)

    new_graph = Graph.objects.get(id=result["graph_id"])
    new_name = f"{graph.name} from {version.name}"
    assert new_graph.name == new_name


@pytest.mark.django_db
def test_create_graph_from_version_appends_suffix_when_name_taken(
    service, graph, default_org
):
    version = service.save_version(graph, name=graph.name)

    result1 = service.create_graph_from_version(version)
    result2 = service.create_graph_from_version(version)

    new_graph1 = Graph.objects.get(id=result1["graph_id"])
    new_graph2 = Graph.objects.get(id=result2["graph_id"])
    # Name must differ from the source graph's name (suffix appended)
    assert new_graph1.name != new_graph2.name
    assert graph.name in new_graph1.name and graph.name in new_graph2.name


@pytest.mark.django_db
def test_create_graph_from_version_round_trips_crew_node(
    service, graph, crew, default_org
):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    version = service.save_version(graph, name="crew-snap")

    result = service.create_graph_from_version(version)

    new_graph = Graph.objects.get(id=result["graph_id"])
    assert new_graph.crew_node_list.count() == 1
    assert new_graph.crew_node_list.first().crew_id == crew.id


@pytest.mark.django_db
def test_create_graph_from_version_with_missing_crew_skips_node_and_warns(
    service, graph, crew, default_org
):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    version = service.save_version(graph, name="crew-snap")
    crew.delete()

    result = service.create_graph_from_version(version)

    new_graph = Graph.objects.get(id=result["graph_id"])
    assert new_graph.crew_node_list.count() == 0
    skipped = [w for w in result["warnings"] if w["type"] == "node_skipped"]
    assert len(skipped) > 0


@pytest.mark.django_db
def test_create_graph_from_version_warnings_node_ids_remap_to_new_ids(
    service, graph, llm_config, default_org
):
    from tables.models import CodeAgentNode

    node = CodeAgentNode.objects.create(
        graph=graph,
        node_name="ca",
        llm_config=llm_config,
    )
    old_snapshot_id = node.id

    version = service.save_version(graph, name="code-agent-snap")
    llm_config.delete()

    result = service.create_graph_from_version(version)

    fk_nulled_warnings = [w for w in result["warnings"] if w["type"] == "fk_nulled"]
    assert len(fk_nulled_warnings) > 0

    new_graph = Graph.objects.get(id=result["graph_id"])
    new_node = new_graph.code_agent_node_list.first()
    assert new_node is not None
    assert fk_nulled_warnings[0]["node_id"] == new_node.id
    assert fk_nulled_warnings[0]["node_id"] != old_snapshot_id


@pytest.mark.django_db
def test_create_graph_from_version_new_graph_has_no_versions(
    service, graph, default_org
):
    version = service.save_version(graph, name="snap")

    result = service.create_graph_from_version(version)

    new_graph = Graph.objects.get(id=result["graph_id"])
    assert new_graph.versions.count() == 0


@pytest.mark.django_db
def test_create_graph_from_version_does_not_mutate_source_graph(
    service, graph, crew, default_org
):
    from tables.models import CrewNode

    CrewNode.objects.create(graph=graph, node_name="cn", crew=crew)
    original_node_count = graph.crew_node_list.count()
    version = service.save_version(graph, name="snap")

    service.create_graph_from_version(version)

    graph.refresh_from_db()
    assert graph.crew_node_list.count() == original_node_count


@pytest.mark.django_db
def test_create_graph_from_version_copies_labels_from_source(
    service, graph, default_org
):
    from tables.models import Label

    label = Label.objects.create(name="urgent")
    graph.labels.set([label])

    version = service.save_version(graph, name="labelled-snap")

    result = service.create_graph_from_version(version)

    new_graph = Graph.objects.get(id=result["graph_id"])
    new_graph_label_ids = set(new_graph.labels.values_list("id", flat=True))
    assert label.id in new_graph_label_ids
