import pytest

from utils.node_label import node_label_from_runtime_name


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
def test_node_label_drops_the_node_id_suffix(runtime_node_name, expected):
    assert node_label_from_runtime_name(runtime_node_name) == expected
