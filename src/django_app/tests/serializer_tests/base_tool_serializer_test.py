import pytest
from tables.serializers.model_serializers import ToolConfigSerializer
from tables.models import ToolConfig
from tables.serializers.serializers import BaseToolSerializer
from tests.fixtures import *



@pytest.mark.django_db
def test_custom_base_tool_serialization(test_tool_with_fields, llm_config, embedding_config):
    tool = test_tool_with_fields
    data = {
        "name": "Config serialization test tool config",
        "tool": tool.pk,
        "configuration": {
            "llm_config": llm_config.pk,
            "embedding_config": embedding_config.pk,
            "url": "http://someurl.com",
        },
    }

    tool_config_serializer = ToolConfigSerializer(data=data)
    tool_config_serializer.is_valid(raise_exception=True)
    tool_config: ToolConfig = tool_config_serializer.save()
    base_tool_serializer = BaseToolSerializer(instance=tool_config)
    print(base_tool_serializer.data)
    assert tool_config.tool.pk == data["tool"]
