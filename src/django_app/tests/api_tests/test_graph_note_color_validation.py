"""A note's backgroundColor is drawn as a CSS background, so only #RRGGBB is stored.

Covers the rule itself and the two write paths that reject a bad colour with 400:
the REST endpoint and bulk save.
"""

import pytest
from django.urls import reverse
from rest_framework import serializers, status

from tables.models.graph_models import GraphNote
from tables.validators.note_metadata import drop_invalid_note_color, validate_note_metadata
from tests.fixtures import *  # noqa: F401,F403

# Every colour the frontend note colour picker offers.
PICKER_COLORS = ["#ffffd1", "#D9D9D9", "#685FFF", "#48CBFF", "#2ABA6B", "#FF8F3F", "#F54242"]

UNSAFE_COLORS = [
    "url(https://attacker.example/pixel.png)",
    "red; background:url(https://attacker.example/pixel.png)",
    "#ffffd1;background:url(https://attacker.example/pixel.png)",
    "expression(alert(1))",
    "var(--other)",
    "red",
    "#fff",
    "#ffffd1ff",
    "#ffffd1\n",
    " #ffffd1",
    "#gggggg",
    "",
    123,
    ["#ffffd1"],
    {"value": "#ffffd1"},
]

BAD_COLOR = "url(https://attacker.example/pixel.png)"
COLOR_ERROR = "'backgroundColor' must be a hex colour in the form #RRGGBB."


# ---- the rule ----


@pytest.mark.parametrize(
    "metadata",
    [
        {},
        {"position": {"x": 1, "y": 2}},
        {"backgroundColor": None},
        *({"backgroundColor": color} for color in PICKER_COLORS),
    ],
)
def test_accepts_absent_null_and_hex_colour(metadata):
    validate_note_metadata(metadata)
    assert drop_invalid_note_color(metadata) == metadata


@pytest.mark.parametrize("color", UNSAFE_COLORS)
def test_rejects_anything_but_hex_colour(color):
    with pytest.raises(serializers.ValidationError):
        validate_note_metadata({"backgroundColor": color})


@pytest.mark.parametrize("color", UNSAFE_COLORS)
def test_normalizer_drops_only_the_bad_colour(color):
    metadata = {"position": {"x": 1, "y": 2}, "size": {"width": 3}, "backgroundColor": color}

    assert drop_invalid_note_color(metadata) == {
        "position": {"x": 1, "y": 2},
        "size": {"width": 3},
    }
    # The stored input is not mutated.
    assert metadata["backgroundColor"] == color


# ---- REST endpoint ----


@pytest.mark.django_db
@pytest.mark.parametrize("color", [BAD_COLOR, "red; background:url(https://a.example/x)"])
def test_rest_create_rejects_unsafe_colour(auth_client, graph, color):
    response = auth_client.post(
        reverse("graphnote-list"),
        {"graph": graph.id, "content": "n", "metadata": {"backgroundColor": color}},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["message"] == f"metadata: {COLOR_ERROR}"
    assert not GraphNote.objects.filter(graph=graph).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("color", [*PICKER_COLORS, None])
def test_rest_create_accepts_picker_colour_and_null(auth_client, graph, color):
    response = auth_client.post(
        reverse("graphnote-list"),
        {"graph": graph.id, "content": "n", "metadata": {"backgroundColor": color}},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert GraphNote.objects.get(graph=graph).metadata == {"backgroundColor": color}


@pytest.mark.django_db
def test_rest_patch_rejects_unsafe_colour_and_keeps_stored_one(auth_client, graph):
    note = GraphNote.objects.create(
        graph=graph, content="n", metadata={"backgroundColor": "#ffffd1"}
    )

    response = auth_client.patch(
        reverse("graphnote-detail", args=[note.pk]),
        {"metadata": {"backgroundColor": BAD_COLOR}},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    note.refresh_from_db()
    assert note.metadata == {"backgroundColor": "#ffffd1"}


# ---- bulk save ----


def _bulk_save(client, graph, notes):
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, "graph_note_list": notes},
        format="json",
    )


@pytest.mark.django_db
def test_bulk_save_rejects_unsafe_colour(auth_client, graph):
    response = _bulk_save(
        auth_client,
        graph,
        [
            {"graph": graph.id, "content": "ok", "metadata": {"backgroundColor": "#685FFF"}},
            {"graph": graph.id, "content": "bad", "metadata": {"backgroundColor": BAD_COLOR}},
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["errors"] == {
        "graph_note_list": [{"index": 1, "errors": {"metadata": [COLOR_ERROR]}}]
    }
    assert not GraphNote.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_bulk_save_accepts_picker_colours(auth_client, graph):
    response = _bulk_save(
        auth_client,
        graph,
        [
            {"graph": graph.id, "content": color, "metadata": {"backgroundColor": color}}
            for color in PICKER_COLORS
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    stored = {
        note.metadata["backgroundColor"] for note in GraphNote.objects.filter(graph=graph)
    }
    assert stored == set(PICKER_COLORS)
