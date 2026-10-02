import contextlib
import json
import re
import sys
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType

from datamodel_code_generator import DataModelType, InputFileType, generate
from datamodel_code_generator.parser.base import title_to_class_name
from pydantic import BaseModel


def generate_model_from_schema(schema_dict: dict) -> type[BaseModel]:
    class_name = title_to_class_name(schema_dict["title"])
    module_name = make_module_name(f"{schema_dict['title']}_{uuid.uuid4().hex[:6]}")
    with TemporaryDirectory() as temporary_directory_name:
        temporary_directory = Path(temporary_directory_name)
        output = Path(temporary_directory / "model.py")
        generate(
            json.dumps(schema_dict),
            input_file_type=InputFileType.JsonSchema,
            output=output,
            # set up the output model types
            output_model_type=DataModelType.PydanticV2BaseModel,
            class_name=class_name,
        )
        class_definition: str = output.read_text()

    dynamic_module = ModuleType(module_name)

    exec(class_definition, dynamic_module.__dict__)  # noqa: S102
    sys.modules[module_name] = dynamic_module
    model: type[BaseModel] = getattr(dynamic_module, class_name)
    recursive_model_rebuild(model)
    return model


def recursive_model_rebuild(model: type[BaseModel], visited: set[type[BaseModel]] | None = None):
    if visited is None:
        visited = set()

    if model in visited:
        return
    visited.add(model)

    with contextlib.suppress(Exception):
        model.model_rebuild(force=True)

    for field in model.model_fields.values():
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            recursive_model_rebuild(annotation, visited)
        else:
            from typing import get_args

            for arg in get_args(annotation):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    recursive_model_rebuild(arg, visited)


def make_module_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if re.match(r"^\d", name):
        name = f"m_{name}"
    return name
