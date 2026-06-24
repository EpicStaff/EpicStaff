from functools import wraps
from typing import Callable, Collection

from crewai.tools.base_tool import Tool

from .args_schema_factory import ArgsSchemaFactory


__all__ = ["CrewToolDynamicFactory"]


class CrewToolDynamicFactory:
    """
    Builds a CrewAI Tool with an args schema generated dynamically from a variable list.
    """

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        variables: Collection[dict],
        resolved_variables: Collection[str],
        func: Callable,
    ) -> Tool:
        args_schema = ArgsSchemaFactory.create(
            tool_name=name,
            variables=variables,
            resolved_variables=resolved_variables,
        )
        return Tool(
            name=name,
            description=description,
            args_schema=args_schema,
            func=cls._wrap_func(func),
        )

    @staticmethod
    def _wrap_func(func: Callable):
        """
        Wrap a function to return raised exceptions as strings.
        """

        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return f"{type(e).__name__}: {e}"

        return wrapper
