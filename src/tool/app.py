import json
import os
from fastapi import FastAPI, Response, status
from models.models import (
    RunToolParamsModel,
    ClassDataResponseModel,
    RunToolResponseModel,
    ToolInitConfigurationModel,
)
from utils import get_tool_data, load_env_from_yaml_config, run_tool, init_tools
from loguru import logger
from tool_factory import DynamicToolFactory, ToolNotFoundException

app = FastAPI()
tool_factory = DynamicToolFactory()
load_env_from_yaml_config("/home/user/root/app/env_config/config.yaml")
init_tools()
os.chdir("savefiles")


@app.post(
    "/tool/{tool_alias}/class-data/",
    status_code=200,
    response_model=ClassDataResponseModel,
)
def get_class_data(
    tool_alias: str, tool_init_configuration: ToolInitConfigurationModel
):
    logger.info(f"{tool_alias}; {tool_init_configuration.model_dump()}")

    try:
        tool = tool_factory.create(
            tool_alias=tool_alias,
            tool_kwargs=tool_init_configuration.tool_init_configuration,
        )
    except ToolNotFoundException as e:
        logger.error(f"Tool class not found by tool alias {tool_alias}")
        return Response(
            content=str(e),
            status_code=status.HTTP_404_NOT_FOUND,
        )
    tool_data = get_tool_data(tool)
    txt = json.dumps(tool_data)
    return ClassDataResponseModel(classdata=txt)


@app.post(
    "/tool/{tool_alias}/run", status_code=200, response_model=RunToolResponseModel
)
def run(tool_alias: str, run_tool_params_model: RunToolParamsModel):
    logger.debug(f"tool/{tool_alias}/run {run_tool_params_model}")
    tool_init_configuration: dict = (
        run_tool_params_model.tool_config.tool_init_configuration or dict()
    )

    tool_kwargs = tool_init_configuration

    config = {}
    if run_tool_params_model.tool_config.llm:
        config["llm"] = run_tool_params_model.tool_config.llm.model_dump(
            exclude_none=True
        )

    if run_tool_params_model.tool_config.embedder:
        config["embedder"] = run_tool_params_model.tool_config.embedder.model_dump(
            exclude_none=True
        )

    if config:
        tool_kwargs["config"] = config

    tool = tool_factory.create(tool_alias=tool_alias, tool_kwargs=tool_kwargs)

    result = run_tool(
        tool=tool,
        run_kwargs=run_tool_params_model.run_kwargs,
    )

    return RunToolResponseModel(data=result)
