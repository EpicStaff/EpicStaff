from importlib import import_module

import pytest

from rbac.models import Organization
from tables.models.mcp_models import McpTool

clamp_migration = import_module("tables.migrations.0259_mcptool_clamp_timeouts")


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Clamp Org")


def _tool(organization, name, **timeouts):
    tool = McpTool.objects.create(
        org=organization, name=name, transport="https://example.com/mcp", tool_name="search"
    )
    McpTool.objects.filter(pk=tool.pk).update(**timeouts)
    return tool


@pytest.mark.django_db
def test_out_of_range_timeouts_are_clamped(organization):
    too_low = _tool(organization, "too-low", timeout=0.5, init_timeout=0)
    too_high = _tool(organization, "too-high", timeout=5000, init_timeout=600)

    clamp_migration.clamp_timeouts(McpTool)

    for tool, expected_timeout, expected_init_timeout in (
        (too_low, 1, 1),
        (too_high, 1800, 120),
    ):
        tool.refresh_from_db()
        assert (tool.timeout, tool.init_timeout) == (expected_timeout, expected_init_timeout)


@pytest.mark.django_db
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_timeouts_take_defaults(organization, value):
    tool = _tool(organization, "non-finite", timeout=value, init_timeout=value)

    clamp_migration.clamp_timeouts(McpTool)

    tool.refresh_from_db()
    assert (tool.timeout, tool.init_timeout) == (30, 10)


@pytest.mark.django_db
def test_in_range_timeouts_are_kept(organization):
    tool = _tool(organization, "in-range", timeout=1800, init_timeout=1.5)

    clamp_migration.clamp_timeouts(McpTool)

    tool.refresh_from_db()
    assert (tool.timeout, tool.init_timeout) == (1800, 1.5)
