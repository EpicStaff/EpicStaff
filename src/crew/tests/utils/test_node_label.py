import pytest

from utils.node_label import runtime_node_name_to_label


@pytest.mark.parametrize(
    ("runtime_name", "expected_label"),
    [
        ("Writer #1 #352", "Writer #1"),
        ("Writer #352", "Writer"),
        # Only the one trailing id suffix goes.
        ("Writer #1 #2 #352", "Writer #1 #2"),
        # No suffix: unchanged.
        ("Writer", "Writer"),
        ("Writer #", "Writer #"),
        ("Writer #12a", "Writer #12a"),
        ("Writer#352", "Writer#352"),
        ("#352 Writer", "#352 Writer"),
        # A newline after the digits is not the end of the name.
        ("Writer #352\n", "Writer #352\n"),
        ("", ""),
    ],
)
def test_runtime_node_name_to_label(runtime_name, expected_label):
    assert runtime_node_name_to_label(runtime_name) == expected_label
