"""Unit tests for rbac.access.delete_collector.build_affected_resources.

Shared by OrganizationManagementService and UserManagementService, which both
fold raw Collector output into the same friendly resource-count map.
"""

from rbac.access.delete_collector import ModelCount, build_affected_resources


def test_build_affected_resources_sums_two_labels_mapping_to_the_same_name():
    by_model = [
        ModelCount(model="tables.PythonCodeTool", count=2),
        ModelCount(model="tables.McpTool", count=3),
    ]
    result = build_affected_resources(by_model)
    assert result == {"tools": 5}


def test_build_affected_resources_excludes_a_known_excluded_label():
    by_model = [ModelCount(model="tables.StartNode", count=4)]
    result = build_affected_resources(by_model)
    assert result == {}


def test_build_affected_resources_folds_in_a_nonzero_external_count():
    result = build_affected_resources([], external_counts={"storage_files": 1})
    assert result == {"storage_files": 1}


def test_build_affected_resources_drops_a_zero_value_external_count():
    result = build_affected_resources([], external_counts={"storage_files": 0})
    assert result == {}


def test_build_affected_resources_merges_external_count_into_existing_db_key():
    by_model = [ModelCount(model="rbac.OrganizationUser", count=2)]
    result = build_affected_resources(by_model, external_counts={"memberships": 3})
    assert result == {"memberships": 5}
