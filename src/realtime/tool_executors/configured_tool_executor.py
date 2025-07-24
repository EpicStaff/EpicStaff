from abc import ABC, abstractmethod
import asyncio
from typing import Any
import aiohttp
from loguru import logger
from models.request_models import (
    ConfiguredToolData,
    ToolInitConfigurationModel,
)
from models.response_models import ToolResponse
from models.ai_models import RealtimeTool, ToolParameters

from utils.pickle_encode import txt_to_obj
from utils.request_utils import post_data_with_retry
from .base_tool_executor import BaseToolExecutor


class ConfiguredToolExecutor(BaseToolExecutor):
    def __init__(self, configured_tool_data: ConfiguredToolData, host: int, port: int):
        super().__init__(tool_name=configured_tool_data.name_alias)
        self.configured_tool_data = configured_tool_data
        self.host = host
        self.port = port
        self._realtime_model = None
        self._lock = asyncio.Lock()

    async def execute(self, **kwargs):
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"http://{self.host}:{self.port}/tool/{self.configured_tool_data.name_alias}/run",
                json={
                    "tool_config": self.configured_tool_data.tool_config.model_dump(),
                    "run_kwargs": kwargs,
                },
            ) as response:
                response_data = await response.json()

        return ToolResponse.model_validate(response_data).data

    async def _gen_configured_realtime_tool_model(
        self, configured_tool_data: ConfiguredToolData
    ) -> RealtimeTool:
        tool_init_configuration = None
        if configured_tool_data.tool_config is not None:
            tool_init_configuration = (
                configured_tool_data.tool_config.tool_init_configuration
            )

        resp = await post_data_with_retry(
            url=f"http://{self.host}:{self.port}/tool/{configured_tool_data.name_alias}/class-data",
            json=ToolInitConfigurationModel(
                tool_init_configuration=tool_init_configuration
            ).model_dump(),
        )
        data_txt = resp["classdata"]
        data: dict = txt_to_obj(data_txt)

        description = data["description"]
        args_schema: dict = data.get("args_schema", dict())

        return RealtimeTool(
            type="function",
            name=self.tool_name,
            description=description,
            parameters=ToolParameters(
                properties=args_schema.get("properties", dict()),
                required=args_schema.get("required", list()),
            ),
        )

    async def get_realtime_tool_model(self) -> RealtimeTool:
        async with self._lock:
            if self._realtime_model is None:
                self._realtime_model = asyncio.create_task(
                    self._gen_configured_realtime_tool_model(self.configured_tool_data)
                )

            return await self._realtime_model
