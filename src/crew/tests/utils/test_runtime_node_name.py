import pytest

from src.shared.runtime_node_name import format_runtime_node_name, parse_runtime_node_label


@pytest.mark.parametrize(
    ("runtime_node_name", "expected"),
    [
        ("Search docs #1 #4512", "Search docs #1"),
        # An unnumbered node runs as "<name> #<id>"; its label is the bare name.
        ("Search docs #4512", "Search docs"),
        ("Name with #hash #12 #99", "Name with #hash #12"),
        ("knowledge_1", "knowledge_1"),
        ("Notes #draft", "Notes #draft"),
        ("#12", "#12"),
        (" #12", " #12"),
    ],
)
def test_parse_runtime_node_label_drops_the_node_id_suffix(runtime_node_name, expected):
    assert parse_runtime_node_label(runtime_node_name) == expected


@pytest.mark.parametrize(
    ("label", "node_id", "expected_name"),
    [
        ("Search docs #1", 4512, "Search docs #1 #4512"),
        ("Search docs", 4512, "Search docs #4512"),
        ("Name with #hash #12", 99, "Name with #hash #12 #99"),
    ],
)
def test_parse_reads_back_the_label_a_runtime_name_was_formatted_from(
    label, node_id, expected_name
):
    runtime_node_name = format_runtime_node_name(label, node_id)

    assert runtime_node_name == expected_name
    assert parse_runtime_node_label(runtime_node_name) == label
