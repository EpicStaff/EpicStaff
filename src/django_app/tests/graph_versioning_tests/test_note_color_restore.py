"""Restoring a version whose note colour is not #RRGGBB succeeds, without that colour."""

import pytest

from tables.models.graph_models import GraphNote
from tests.fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_restore_of_a_version_with_unsafe_colour_succeeds_without_it(service, graph):
    # Written through the ORM, as a note stored before the API checked the colour.
    GraphNote.objects.create(
        graph=graph,
        content="legacy",
        metadata={
            "position": {"x": 10, "y": 20},
            "backgroundColor": "red; background:url(https://attacker.example/pixel.png)",
        },
    )
    version = service.save_version(graph, name="v")

    graph.refresh_from_db()
    service.restore_version(version, expected_save_version=graph.save_version)

    [note] = GraphNote.objects.filter(graph=graph)
    assert note.content == "legacy"
    assert note.metadata == {"position": {"x": 10, "y": 20}}
