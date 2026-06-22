from dataclasses import dataclass
import json
from pathlib import Path

from tables.models import PythonCodeTool, PythonCode
import yaml
from django.db import transaction
from loguru import logger


@dataclass
class ToolData:
    name: str
    description: str
    args_schema: str
    code_file: str
    entrypoint: str
    requirements: str
    use_storage: bool = False


BASE_FOLDER_PATH: Path = Path("../shared/tools").absolute().resolve()
TOOL_DATA_FILE_NAME = "tool_data.yaml"


def get_all_tool_paths() -> list[Path]:
    return [
        p for p in BASE_FOLDER_PATH.iterdir() if p.is_dir() and p.name.endswith("_tool")
    ]


def get_tool_data(tool_path: Path) -> ToolData:
    tool_data_file = tool_path / TOOL_DATA_FILE_NAME
    with tool_data_file.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    tool_data = data.get("tool-data", {})
    return ToolData(
        name=tool_data.get("name", ""),
        description=tool_data.get("description", ""),
        args_schema=tool_data.get("args-schema", ""),
        code_file=tool_data.get("code-file", ""),
        entrypoint=tool_data.get("entrypoint", ""),
        requirements=tool_data.get("requirements", ""),
        use_storage=tool_data.get("use-storage", False),
    )


def get_args_schema(tool_path: Path, args_schema_file_name: str) -> dict:
    args_schema_file = tool_path / args_schema_file_name

    with args_schema_file.open("r", encoding="utf-8") as f:
        args_schema = json.load(f)
    return args_schema


def get_requirements(tool_path: Path, requirements_file_name: str) -> list[str]:
    requirements_file = tool_path / requirements_file_name
    if not requirements_file.exists():
        return []

    with open(requirements_file, "r", encoding="utf-8") as f:
        lines = f.readlines()

    requirements = [
        line.strip()
        for line in lines
        if line.strip() and not line.strip().startswith("#")
    ]

    return requirements


def get_code_file(tool_path: Path, code_file_name: str) -> str:
    with open(tool_path / code_file_name, "r", encoding="utf-8") as f:
        code = f.read()
    return code


def args_schema_to_variables(args_schema: dict) -> list[dict]:
    properties = args_schema.get("properties", {})
    required_names = set(args_schema.get("required", []))
    variables = []
    for name, prop in properties.items():
        var = {
            "name": name,
            "type": prop.get("type", "string"),
            "description": prop.get("description", ""),
            "default_value": prop.get("default", None),
            "input_type": "agent_input",
            "required": name in required_names,
        }
        if prop.get("properties"):
            var["properties"] = prop["properties"]
        if prop.get("required"):
            var["required_properties"] = prop["required"]
        if prop.get("items"):
            var["item"] = prop["items"]
        variables.append(var)
    return variables


def create_or_update_python_tool(
    name: str,
    code: str,
    requirements: str,
    entrypoint: str,
    description: str,
    args_schema: dict,
    variables: list[dict],
    use_storage: bool = False,
) -> PythonCodeTool:
    python_tool_obj = PythonCodeTool.objects.filter(name=name).first()

    if python_tool_obj is None:
        python_code_obj = PythonCode.objects.create(
            code=code, entrypoint=entrypoint, libraries=requirements
        )
        python_tool_obj = PythonCodeTool.objects.create(
            name=name,
            python_code=python_code_obj,
            description=description,
            variables=variables,
            built_in=True,
            use_storage=use_storage,
        )
        return python_tool_obj
    else:
        python_code_obj: PythonCode = python_tool_obj.python_code
        python_code_obj.code = code
        python_code_obj.entrypoint = entrypoint
        python_code_obj.libraries = requirements
        python_tool_obj.description = description
        python_tool_obj.args_schema = args_schema
        python_tool_obj.variables = variables
        python_tool_obj.use_storage = use_storage
        python_tool_obj.save()
        python_code_obj.save()
        return python_tool_obj


def upload_tools():
    with transaction.atomic():
        tool_path_list = get_all_tool_paths()
        tool_name_set: set[str] = set()
        for tool_path in tool_path_list:
            try:
                tool_data = get_tool_data(tool_path)
                args_schema = get_args_schema(
                    tool_path=tool_path, args_schema_file_name=tool_data.args_schema
                )
                variables = args_schema_to_variables(args_schema)
                code = get_code_file(
                    tool_path=tool_path, code_file_name=tool_data.code_file
                )
                requirements = get_requirements(
                    tool_path=tool_path, requirements_file_name=tool_data.requirements
                )
                requirements_string = " ".join(requirements)
                name = tool_data.name
                entrypoint = tool_data.entrypoint
                description = tool_data.description
                create_or_update_python_tool(
                    name=name,
                    code=code,
                    requirements=requirements_string,
                    entrypoint=entrypoint,
                    description=description,
                    args_schema=args_schema,
                    variables=variables,
                    use_storage=tool_data.use_storage,
                )
                tool_name_set.add(name)
            except FileNotFoundError as e:
                logger.error(f"Error processing {tool_path}: {e}")

        db_tools: set[str] = set(
            PythonCodeTool.objects.filter(built_in=True).values_list("name", flat=True)
        )
        to_delete = db_tools.difference(tool_name_set)

        PythonCodeTool.objects.filter(name__in=to_delete).delete()
