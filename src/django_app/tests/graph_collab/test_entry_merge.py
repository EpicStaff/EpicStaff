"""Unit tests for tables.graph_collab.entry_merge.

Pure-function tests — no DB, no Redis. Covers deep_merge (the metadata
sub-merge primitive), merge_entry (the top-level merge policy used
by _apply_node_merge), and find_mismatched_keys (the CAS precondition helper).
"""

from tables.graph_collab.entry_merge import (
    deep_merge,
    find_mismatched_keys,
    merge_entry,
)


def test_nested_dicts_recurse():
    base = {"python_code": {"code": "old", "libraries": ["requests"]}}
    overlay = {"python_code": {"code": "new"}}

    result = deep_merge(base, overlay)

    assert result == {"python_code": {"code": "new", "libraries": ["requests"]}}


def test_list_value_is_replaced_whole_not_merged():
    base = {"condition_groups": [{"id": 1}, {"id": 2}]}
    overlay = {"condition_groups": [{"id": 3}]}

    result = deep_merge(base, overlay)

    assert result["condition_groups"] == [{"id": 3}]


def test_scalar_overlay_wins():
    base = {"node_name": "old name", "crew_id": 5}
    overlay = {"node_name": "new name"}

    result = deep_merge(base, overlay)

    assert result == {"node_name": "new name", "crew_id": 5}


def test_none_overlay_value_wins_over_existing_scalar():
    base = {"output_variable_path": "some.path"}
    overlay = {"output_variable_path": None}

    result = deep_merge(base, overlay)

    assert result["output_variable_path"] is None


def test_absent_keys_in_overlay_are_preserved():
    base = {"id": 1, "crew_id": 5, "node_name": "Crew #1", "metadata": {"x": 1}}
    overlay = {"node_name": "Crew #1 renamed"}

    result = deep_merge(base, overlay)

    assert result["id"] == 1
    assert result["crew_id"] == 5
    assert result["metadata"] == {"x": 1}
    assert result["node_name"] == "Crew #1 renamed"


def test_dict_vs_non_dict_type_mismatch_overlay_replaces_whole():
    base = {"metadata": {"position": {"x": 0, "y": 0}}}
    overlay = {"metadata": "not-a-dict-anymore"}

    result = deep_merge(base, overlay)

    assert result["metadata"] == "not-a-dict-anymore"


def test_non_dict_base_dict_overlay_replaces_whole():
    base = {"metadata": None}
    overlay = {"metadata": {"position": {"x": 1, "y": 2}}}

    result = deep_merge(base, overlay)

    assert result["metadata"] == {"position": {"x": 1, "y": 2}}


def test_returns_new_dict_base_is_not_mutated():
    base = {"python_code": {"code": "old", "libraries": ["requests"]}}
    overlay = {"python_code": {"code": "new"}}

    result = deep_merge(base, overlay)

    assert base == {"python_code": {"code": "old", "libraries": ["requests"]}}
    assert result is not base
    assert result["python_code"] is not base["python_code"]


def test_overlay_is_not_mutated():
    base = {"metadata": {"a": 1}}
    overlay = {"metadata": {"b": 2}}

    result = deep_merge(base, overlay)

    assert overlay == {"metadata": {"b": 2}}
    assert result["metadata"] == {"a": 1, "b": 2}


def test_nested_dict_in_result_is_not_shared_reference_with_base():
    nested = {"code": "old"}
    base = {"python_code": nested}
    overlay = {}

    result = deep_merge(base, overlay)

    result["python_code"]["code"] = "mutated"
    assert nested["code"] == "old"


def test_empty_overlay_returns_equivalent_copy_of_base():
    base = {"id": 1, "metadata": {"x": 1}}

    result = deep_merge(base, {})

    assert result == base
    assert result is not base


# ---------------------------------------------------------------------------
# merge_entry — top-level merge policy
# ---------------------------------------------------------------------------


def test_merge_entry_non_metadata_nested_dict_replaced_whole():
    base = {
        "python_code": {
            "code": "old",
            "libraries": ["requests"],
            "global_kwargs": {"a": 1},
        }
    }
    overlay = {"python_code": {"code": "new", "libraries": [], "global_kwargs": {}}}

    result = merge_entry(base, overlay)

    assert result["python_code"] == {
        "code": "new",
        "libraries": [],
        "global_kwargs": {},
    }


def test_merge_entry_metadata_sub_merged_preserves_siblings():
    base = {
        "metadata": {
            "position": {"x": 0, "y": 0},
            "size": {"width": 100, "height": 50},
            "color": "#fff",
            "nodeNumber": 3,
        }
    }
    overlay = {"metadata": {"position": {"x": 100, "y": 200}}}

    result = merge_entry(base, overlay)

    assert result["metadata"] == {
        "position": {"x": 100, "y": 200},
        "size": {"width": 100, "height": 50},
        "color": "#fff",
        "nodeNumber": 3,
    }


def test_merge_entry_user_key_deletion_propagates():
    base = {"input_map": {"a": 1, "b": 2}}
    overlay = {"input_map": {"a": 1}}

    result = merge_entry(base, overlay)

    assert result["input_map"] == {"a": 1}
    assert "b" not in result["input_map"]


def test_merge_entry_does_not_mutate_inputs_and_returns_new_dict():
    base = {"python_code": {"code": "old"}, "metadata": {"position": {"x": 0, "y": 0}}}
    overlay = {
        "python_code": {"code": "new"},
        "metadata": {"position": {"x": 1, "y": 1}},
    }

    result = merge_entry(base, overlay)

    assert base == {
        "python_code": {"code": "old"},
        "metadata": {"position": {"x": 0, "y": 0}},
    }
    assert overlay == {
        "python_code": {"code": "new"},
        "metadata": {"position": {"x": 1, "y": 1}},
    }
    assert result is not base
    assert result["python_code"] is not overlay["python_code"]
    assert result["metadata"] is not base["metadata"]


def test_merge_entry_absent_keys_preserved():
    base = {"id": 1, "crew_id": 5, "node_name": "Crew #1"}
    overlay = {"node_name": "Renamed"}

    result = merge_entry(base, overlay)

    assert result == {"id": 1, "crew_id": 5, "node_name": "Renamed"}


# ---------------------------------------------------------------------------
# find_mismatched_keys — CAS precondition helper
# ---------------------------------------------------------------------------


def test_find_mismatched_keys_scalar_match_and_mismatch():
    base = {"node_name": "Current"}

    assert find_mismatched_keys(base, {"node_name": "Current"}) == []
    assert find_mismatched_keys(base, {"node_name": "Stale"}) == ["node_name"]


def test_find_mismatched_keys_whole_value_dict_compare_for_non_metadata():
    base = {"input_map": {"a": 1, "b": 2}}

    # Whole-value compare: an extra key in base is a mismatch even though
    # the expected value doesn't declare it deleted (matches whole-replace).
    assert find_mismatched_keys(base, {"input_map": {"a": 1}}) == ["input_map"]
    assert find_mismatched_keys(base, {"input_map": {"a": 1, "b": 2}}) == []


def test_find_mismatched_keys_metadata_compares_only_present_sub_keys():
    base = {"metadata": {"position": {"x": 0, "y": 0}, "color": "red"}}

    # "color" differs freely — only "position" is present in expected, so
    # only "position" is compared.
    result = find_mismatched_keys(base, {"metadata": {"position": {"x": 0, "y": 0}}})
    assert result == []

    result = find_mismatched_keys(
        base, {"metadata": {"position": {"x": 999, "y": 999}}}
    )
    assert result == ["metadata.position"]


def test_find_mismatched_keys_missing_base_key_equals_expected_none():
    base = {}

    assert find_mismatched_keys(base, {"node_name": None}) == []
    assert find_mismatched_keys(base, {"metadata": {"color": None}}) == []
