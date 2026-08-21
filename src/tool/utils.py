from pathlib import Path
from dotenv import load_dotenv
import os
from typing import Any
import yaml
from base_models import Callable
from pickle_encode import txt_to_obj
from langchain_core.tools import BaseTool
from langchain_core.tools import create_schema_from_function
from parse_model_data import CallableParser
from tool_factory import DynamicToolFactory
from loguru import logger

cp: CallableParser = CallableParser()


def load_tool_alias_callable_dict() -> dict[str, Callable]:
    load_dotenv()
    tool_alias_callable_dict_txt = os.environ.get("ALIAS_CALLABLE")
    tool_alias_callable_dict: dict[str, Callable] = txt_to_obj(
        tool_alias_callable_dict_txt
    )
    logger.debug(f"loaded tool alias: {tool_alias_callable_dict}")
    return tool_alias_callable_dict


def register_tools_in_tool_factory(
    tool_alias_callable_dict: dict[str, Callable]
) -> None:

    tool_factory = DynamicToolFactory()
    for alias, tool_callable in tool_alias_callable_dict.items():
        tool_class, tool_args, tool_kwargs = cp.eval_callable(
            callable=tool_callable, eval=False
        )

        tool_factory.register_tool_class(
            tool_alias=alias,
            tool_class=tool_class,
            default_args=tuple(tool_args),
            default_kwargs=tool_kwargs,
        )
        logger.info(f"registered {alias}")


def init_tools() -> None:
    """
    Initialize all tools in tool factory using ALIAS_CALLABLE variable from dotenv file
    """
    tool_alias_callable_dict = load_tool_alias_callable_dict()
    register_tools_in_tool_factory(tool_alias_callable_dict)


def run_tool(
    tool,
    run_kwargs: dict[str, Any],
):
    """
    Run tool with args and kwargs
    """

    return tool._run(**run_kwargs)


def create_tool_class(callable: Callable) -> tuple[BaseTool, tuple, dict]:
    """
    Create BaseTool class `base_models.Callable`, evaluating nested callables
    """
    return cp.eval_callable(callable=callable, eval=False)


def get_tool_data(tool: BaseTool) -> dict:
    """
    Creates tool dict schema from tool using it's name, description and args_schema.

    If args_schema doesn't exist, creates it from `_run` method.
    """
    tool_dict = tool.dict(include={"name", "description", "args_schema"})

    args_schema = tool_dict.get("args_schema")
    if args_schema is None:
        args_schema = create_schema_from_function(
            f"{tool.__class__.__name__}Input", tool._run
        )

    return {
        "name": tool_dict["name"],
        "description": tool_dict["description"],
        "args_schema": args_schema.schema(),
    }


def load_env_from_yaml_config(yaml_config_path):
    loaded = False
    try:
        with open(Path(yaml_config_path).resolve()) as f:
            cfg: dict = yaml.load(f, Loader=yaml.FullLoader)
        for k, v in cfg.items():
            os.environ[k] = v
            logger.info(f"loaded {k}")

        loaded = True
    except Exception as e:
        logger.error(e)

    return loaded
