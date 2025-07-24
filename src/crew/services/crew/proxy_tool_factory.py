import time
from typing import Any, Type
from crewai.tools.base_tool import Tool
from models.request_models import CodeResultData, CodeTaskData
from services.redis_service import RedisService
from models.response_models import ToolResponse
from models.request_models import (
    PythonCodeToolData,
    ConfiguredToolData,
    ToolInitConfigurationModel,
)
from crewai.tools import BaseTool
import requests
from pydantic import BaseModel
from services.schema_converter.converter import generate_model_from_schema
from services.pickle_encode import txt_to_obj
from loguru import logger
from services.run_python_code_service import RunPythonCodeService
import asyncio


class ProxyToolFactory:

    def __init__(
        self,
        host: str,
        port: int,
        redis_service: RedisService,
        python_code_executor_service: RunPythonCodeService,
    ):
        self.host = host
        self.port = port
        self.redis_service = redis_service
        self.python_code_executor_service = python_code_executor_service
        self.loop = asyncio.get_event_loop()

    def create_python_code_proxy_tool(
        self, python_code_tool_data: PythonCodeToolData, global_kwargs: dict[str, Any]
    ):
        args_schema = generate_model_from_schema(python_code_tool_data.args_schema)
        args_schema.model_rebuild()
        name = python_code_tool_data.name
        description = python_code_tool_data.description

        def _run(*_, **kwargs):
            # TODO: fix workaround after making crewai async

            future = asyncio.run_coroutine_threadsafe(
                self.python_code_executor_service.run_code(
                    python_code_data=python_code_tool_data.python_code,
                    inputs=kwargs,
                    additional_global_kwargs=global_kwargs,
                ),
                self.loop,
            )
            result: dict = future.result()

            if result["returncode"] == 0:
                return result["result_data"]
            else:
                return result["stderr"]

        return Tool(
            name=name, description=description, args_schema=args_schema, func=_run
        )

    def create_proxy_tool(self, tool_data: ConfiguredToolData) -> Type[BaseTool]:

        tool_init_configuration = None
        if tool_data.tool_config is not None:
            tool_init_configuration = tool_data.tool_config.tool_init_configuration

        resp = self.post_data_with_retry(
            url=f"http://{self.host}:{self.port}/tool/{tool_data.name_alias}/class-data",
            json=ToolInitConfigurationModel(
                tool_init_configuration=tool_init_configuration
            ).model_dump(),
        )
        data_txt = resp.json()["classdata"]
        data: dict = txt_to_obj(data_txt)
        data["args_schema"] = generate_model_from_schema(
            data["args_schema"]
        )  # TODO: rename
        data["args_schema"].model_rebuild()

        logger.info(data)

        proxy_tool_factory = self  # VERY BAD CODE!!

        def _run(*_, **kwargs):  # _ is for self
            logger.info(f"Entered modified run method: \nkwargs = {kwargs}")

            kw: dict = kwargs.get("kwargs", dict())
            exclude_keys = {"args", "kwargs"}

            other_kw = {k: v for k, v in kwargs.items() if k not in exclude_keys}

            kw.update(other_kw)

            logger.info(f"kwargs = {kw}")

            return proxy_tool_factory.run_tool_in_container(
                tool_data=tool_data, run_kwargs=kw
            )

        return Tool(
            name=data["name"],
            description=data["description"],
            args_schema=data["args_schema"],
            func=_run,
        )

    def run_tool_in_container(
        self,
        tool_data: ConfiguredToolData,
        run_kwargs: dict[str, Any],
    ) -> str:

        response = requests.post(
            url=f"http://{self.host}:{self.port}/tool/{tool_data.name_alias}/run",
            json={
                "tool_config": tool_data.tool_config.model_dump(),
                "run_kwargs": run_kwargs,
            },
        )

        return ToolResponse.model_validate(response.json()).data

    # TODO: make async
    def fetch_data_with_retry(self, url, retries=15, delay=3):
        for attempt in range(retries):
            try:
                print(f"Attempt {attempt + 1} to fetch data...")
                resp = requests.get(url)
                if resp.status_code == 200:
                    return resp
            except requests.exceptions.RequestException as e:
                print(f"Request failed: {e}")
            # Wait before retrying
            if attempt < retries - 1:
                time.sleep(delay)
        raise Exception(f"Failed to fetch data after {retries} attempts.")

    def post_data_with_retry(self, url, json=None, retries=15, delay=3):
        if json is None:
            json = dict()

        for attempt in range(retries):
            try:
                print(f"Attempt {attempt + 1} to fetch data...")
                resp = requests.post(url=url, json=json)
                if resp.status_code == 200:
                    return resp
            except requests.exceptions.RequestException as e:
                print(f"Request failed: {e}")
            # Wait before retrying
            if attempt < retries - 1:
                time.sleep(delay)
        raise Exception(f"Failed to post data after {retries} attempts.")
