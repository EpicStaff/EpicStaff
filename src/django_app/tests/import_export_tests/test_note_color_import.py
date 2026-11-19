"""Importing a flow drops a note colour that is not #RRGGBB instead of failing the flow."""

import pytest

from tables.import_export.enums import EntityType
from tables.import_export.schemas import ImportSettings
from tables.models import Graph
from tables.models.graph_models import GraphNote
from tests.helpers import UNRESTRICTED_EXPORT_POLICY


def _export_and_import(export_service, import_service, source: Graph) -> Graph:
    export_data = export_service.export_entities(
        EntityType.GRAPH, [source.id], policy=UNRESTRICTED_EXPORT_POLICY
    ).data
    id_mapper, _ = import_service.import_data(
        export_data, EntityType.GRAPH, settings=ImportSettings()
    )
    return Graph.objects.get(pk=id_mapper.get(EntityType.GRAPH, source.id))


@pytest.mark.django_db
def test_import_drops_unsafe_colour_and_keeps_the_note(
    export_service, import_service, default_org
):
    source = Graph.objects.create(name="flow", org=default_org)
    # Written through the ORM: a file can carry any value, the API never would.
    GraphNote.objects.create(
        graph=source,
        content="legacy",
        metadata={
            "position": {"x": 10, "y": 20},
            "backgroundColor": "url(https://attacker.example/pixel.png)",
        },
    )

    imported = _export_and_import(export_service, import_service, source)

    [note] = GraphNote.objects.filter(graph=imported)
    assert note.content == "legacy"
    assert note.metadata == {"position": {"x": 10, "y": 20}}


@pytest.mark.django_db
def test_import_keeps_a_valid_colour(export_service, import_service, default_org):
    source = Graph.objects.create(name="flow", org=default_org)
    GraphNote.objects.create(graph=source, content="n", metadata={"backgroundColor": "#2ABA6B"})

    imported = _export_and_import(export_service, import_service, source)

    assert GraphNote.objects.get(graph=imported).metadata == {"backgroundColor": "#2ABA6B"}
