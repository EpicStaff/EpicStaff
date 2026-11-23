import pytest

from rest_framework import serializers

from tables.serializers.utils.bulk_ids import BulkIdListField

# Nothing here touches the database, but the session-scoped autouse flush in
# tests/conftest.py needs the test database set up (see test_env_bool.py).
pytestmark = pytest.mark.django_db


class ItemIdsSerializer(serializers.Serializer):
    item_ids = BulkIdListField()


@pytest.mark.parametrize(
    "item_ids",
    [[1], [7, 3, 7], list(range(1, 501))],
    ids=["one", "order-and-repeats-kept", "exactly-500"],
)
def test_accepts_a_list_of_positive_integers(item_ids):
    serializer = ItemIdsSerializer(data={"item_ids": item_ids})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["item_ids"] == item_ids


LIST_OF_IDS = "Must be a list of positive integers."


@pytest.mark.parametrize(
    ("body", "expected_code", "expected_message"),
    [
        ({"item_ids": [True]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [False]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [1, True]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": ["1"]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": ["x"]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [1.0]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [1.5]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [0]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [-1]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [None]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": [[1]]}, "invalid_item", LIST_OF_IDS),
        ({"item_ids": "1"}, "not_a_list", LIST_OF_IDS),
        ({"item_ids": 1}, "not_a_list", LIST_OF_IDS),
        ({"item_ids": {"1": 1}}, "not_a_list", LIST_OF_IDS),
        ({"item_ids": None}, "null", LIST_OF_IDS),
        ({"item_ids": []}, "empty", "Must not be empty."),
        ({}, "required", "This field is required."),
        ({"item_ids": list(range(1, 502))}, "max_length", "Must have at most 500 items."),
        ({"item_ids": ["x"] * 501}, "max_length", "Must have at most 500 items."),
    ],
    ids=[
        "true",
        "false",
        "bool-among-ints",
        "numeric-string",
        "string",
        "whole-float",
        "float",
        "zero",
        "negative",
        "null-item",
        "nested-list",
        "string-instead-of-list",
        "int-instead-of-list",
        "object-instead-of-list",
        "null",
        "empty",
        "missing",
        "501-ids",
        "501-junk-items",
    ],
)
def test_rejects_anything_else_with_one_sentence_on_the_field(body, expected_code, expected_message):
    serializer = ItemIdsSerializer(data=body)

    assert not serializer.is_valid()
    assert serializer.errors == {"item_ids": [expected_message]}
    assert [error.code for error in serializer.errors["item_ids"]] == [expected_code]
