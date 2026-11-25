import pytest

from tables.models import McpTool
from tables.services.converter_service import ConverterService


@pytest.mark.django_db
def test_mcp_tool_payload_carries_the_epicstaff_name_beside_the_server_tool_name(default_org):
    tool = McpTool.objects.create(
        name="echo-b",
        transport="https://mcp.example.test/sse",
        tool_name="echo",
        org=default_org,
    )

    data = ConverterService().convert_mcp_tool_to_pydantic(tool)

    assert (data.name, data.tool_name) == ("echo-b", "echo")
