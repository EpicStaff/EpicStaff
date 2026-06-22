import asyncio
from typing import Any, Optional

from crewai.tools.base_tool import Tool

from services.run_python_code_service import RunPythonCodeService
from services.graph.events import StopEvent
from src.shared.models import PythonCodeToolData

from .crew_tool_dynamic_factory import CrewToolDynamicFactory


__all__ = ["PythonCodeToolFactory"]


class PythonCodeToolFactory:
    """
    Builds CrewAI Tool that runs a user-defined Python code in the sandbox service.
    """

    def __init__(
        self,
        executor: RunPythonCodeService,
        asyncio_loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self.python_code_executor = executor
        self.asyncio_loop = asyncio_loop or asyncio.get_event_loop()

    def create(
        self,
        data: PythonCodeToolData,
        global_kwargs: dict[str, Any],
        stop_event: StopEvent,
    ) -> Tool:
        python_code_global_kwargs = data.python_code.global_kwargs or {}

        def run(*_, **kwargs):
            # TODO: fix workaround after making crewai async
            inputs = {**python_code_global_kwargs, **kwargs}
            future = asyncio.run_coroutine_threadsafe(
                self.python_code_executor.run_code(
                    python_code_data=data.python_code,
                    inputs=inputs,
                    additional_global_kwargs=global_kwargs,
                    stop_event=stop_event,
                ),
                self.asyncio_loop,
            )
            result: dict = future.result()

            if result["returncode"] == 0:
                return result["result_data"]
            else:
                return result["stderr"]

        return CrewToolDynamicFactory.create(
            name=data.name,
            description=data.description,
            variables=data.variables,
            resolved_variables=set(python_code_global_kwargs.keys()),
            func=run,
        )
