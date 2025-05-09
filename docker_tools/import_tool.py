from enum import Enum
from docker.models.images import Image

from build_langchain_tool import ToolDockerImageBuilder, get_image_by_name, client
from base_models import *
from proxy_tool_builder import ProxyToolBuilder


def import_tools(import_tool_data: ImportToolData):
    dependencies = import_tool_data.dependencies
    force_build = import_tool_data.force_build

    if dependencies is None:
        dependencies = []

    tdib = ToolDockerImageBuilder(
        tool_dict=import_tool_data.tool_dict,
        import_list=dependencies,
    )

    image: Image | None = get_image_by_name(
        image_name=import_tool_data.image_name
    )  # optimize

    if force_build or not image:
        image = tdib.build_tool(image_name=import_tool_data.image_name)[0]

    # TODO: refactor

    port = 5005

    container_tool = client.containers.run(
        image=image, ports={"8000/tcp": port}, detach=True
    )

    tool_alias_dict = dict()
    for alias in import_tool_data.tool_dict.keys():
        tool_alias_dict[alias] = ProxyToolBuilder(
            tool_alias=alias, image=image, port=port
        ).build()

    return tool_alias_dict
