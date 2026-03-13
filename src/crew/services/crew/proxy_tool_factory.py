from typing import Any
import time
import concurrent.futures
import asyncio
import requests
from loguru import logger


from crewai.tools.base_tool import Tool

from src.crew.models.response_models import ToolResponse
from src.shared.models import (
    PythonCodeToolData,
    ConfiguredToolData,
    ToolInitConfigurationModel,
)

from src.crew.services.graph.events import StopEvent
from src.crew.services.schema_converter.converter import generate_model_from_schema
from src.crew.services.pickle_encode import txt_to_obj
from src.crew.services.run_python_code_service import RunPythonCodeService


class ProxyToolFactory:
    def __init__(
        self,
        host: str,
        port: int,
        python_code_executor_service: RunPythonCodeService,
    ):
        self.host = host
        self.port = port
        self.python_code_executor_service = python_code_executor_service
        self.loop = asyncio.get_event_loop()

    def create_python_code_proxy_tool(
        self,
        python_code_tool_data: PythonCodeToolData,
        global_kwargs: dict[str, Any],
        stop_event: StopEvent,
    ) -> Tool:
        args_schema_raw = python_code_tool_data.args_schema
        args_schema_dict = (
            args_schema_raw
            if isinstance(args_schema_raw, dict)
            else args_schema_raw.model_dump()
        )
        args_schema = generate_model_from_schema(args_schema_dict)
        name = python_code_tool_data.name
        description = python_code_tool_data.description

        def _run(*_, **kwargs):
            # TODO: fix workaround after making crewai async
            python_code_kwargs = (
                python_code_tool_data.python_code.global_kwargs or dict()
            )
            inputs = {**python_code_kwargs, **kwargs}
            future = asyncio.run_coroutine_threadsafe(
                self.python_code_executor_service.run_code(
                    python_code_data=python_code_tool_data.python_code,
                    inputs=inputs,
                    additional_global_kwargs=global_kwargs,
                    stop_event=stop_event,
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

    def create_proxy_tool(
        self,
        tool_data: ConfiguredToolData,
        stop_event: StopEvent | None = None,
    ) -> Tool:
        tool_init_configuration = None
        if tool_data.tool_config is not None:
            tool_init_configuration = tool_data.tool_config.tool_init_configuration

        resp = self.post_data_with_retry(
            url=f"http://{self.host}:{self.port}/tool/{tool_data.name_alias}/class-data",
            json=ToolInitConfigurationModel(
                tool_init_configuration=tool_init_configuration
            ).model_dump(),
            stop_event=stop_event,
        )
        data_txt = resp.json()["classdata"]
        data: dict = txt_to_obj(data_txt)
        data["args_schema"] = generate_model_from_schema(
            data["args_schema"]
        )  # TODO: rename

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
                tool_data=tool_data,
                run_kwargs=kw,
                stop_event=stop_event,
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
        stop_event: StopEvent | None = None,
    ) -> str:
        response = self.post_data_with_retry(
            url=f"http://{self.host}:{self.port}/tool/{tool_data.name_alias}/run",
            json={
                "tool_config": tool_data.tool_config.model_dump(),
                "run_kwargs": run_kwargs,
            },
            retries=3,
            stop_event=stop_event,
        )

        return ToolResponse.model_validate(response.json()).data

    def post_data_with_retry(
        self, url, json=None, retries=15, delay=3, stop_event: StopEvent | None = None
    ):
        if json is None:
            json = {}

        for attempt in range(retries):
            try:
                logger.info(f"Attempt {attempt + 1} to post data...")
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(requests.post, url, json=json)

                    while True:
                        if stop_event is not None:
                            stop_event.check_stop()

                        try:
                            resp = future.result(timeout=0.01)
                            if resp.status_code == 200:
                                return resp
                            else:
                                logger.error(f"Bad status: {resp.status_code}")
                                break
                        except concurrent.futures.TimeoutError:
                            continue

            except requests.exceptions.RequestException as e:
                logger.error(f"Request failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay)

        raise Exception(f"Failed to post data after {retries} attempts.")
