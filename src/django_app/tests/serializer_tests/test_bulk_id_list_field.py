import pytest

from tables.serializers.utils.bulk_ids import BulkIdListField, BulkIdListSerializer

# Nothing here touches the database, but the session-scoped autouse flush in
# tests/conftest.py needs the test database set up (see test_env_bool.py).
pytestmark = pytest.mark.django_db


class ItemIdsSerializer(BulkIdListSerializer):
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


@pytest.mark.parametrize(
    ("body", "expected_message"),
    [
        ({"item_ids": [True]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [False]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [1, True]}, "item_ids must be a list of positive integers."),
        ({"item_ids": ["1"]}, "item_ids must be a list of positive integers."),
        ({"item_ids": ["x"]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [1.0]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [1.5]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [0]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [-1]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [None]}, "item_ids must be a list of positive integers."),
        ({"item_ids": [[1]]}, "item_ids must be a list of positive integers."),
        ({"item_ids": "1"}, "item_ids must be a list of positive integers."),
        ({"item_ids": 1}, "item_ids must be a list of positive integers."),
        ({"item_ids": {"1": 1}}, "item_ids must be a list of positive integers."),
        ({"item_ids": None}, "item_ids must be a list of positive integers."),
        ({"item_ids": []}, "item_ids must not be empty."),
        ({}, "item_ids is required."),
        ({"item_ids": list(range(1, 502))}, "item_ids must have at most 500 items."),
        ({"item_ids": ["x"] * 501}, "item_ids must have at most 500 items."),
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
def test_rejects_anything_else_with_one_sentence(body, expected_message):
    serializer = ItemIdsSerializer(data=body)

    assert not serializer.is_valid()
    assert serializer.error_message == expected_message


def test_a_body_that_is_not_an_object_reports_the_non_field_error():
    serializer = ItemIdsSerializer(data=[1, 2])

    assert not serializer.is_valid()
    assert serializer.error_message == "Invalid data. Expected a dictionary, but got list."

