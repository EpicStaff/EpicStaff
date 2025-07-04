from typing import Any, Union
import typing
from pydantic import BaseModel


class Callable(BaseModel):
    module_path: str | None = None
    class_name: str
    package: str | None = None
    args: list[Union["Callable", typing.Iterable, typing.Dict]] | None = None
    kwargs: dict[str, Union[str, "Callable", typing.Iterable, typing.Dict]] | None = (
        None
    )


class ImportToolData(BaseModel):
    callable: Callable
    dependencies: list[str] | None = None
    force_build: bool = False



