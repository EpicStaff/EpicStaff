import importlib
import pkgutil
import typing
from base_models import Callable
from langchain_core.tools import BaseTool
from loguru import logger


class CallableParser:
    def import_callable(self, class_name: str, module_path: str) -> typing.Callable:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def find_tool(self, class_name: str, package_name: str) -> typing.Type | None:
        """
        Recursively search through the target packages for the tool classes and their paths.

        Returns:
            Found tool class or `None` if not found
        """

        try:
            package = importlib.import_module(package_name)
            pkg_name = package.__name__

            if not hasattr(package, "__path__"):
                return getattr(package, class_name, None)

            pkg_path = package.__path__
            for module_info in pkgutil.walk_packages(pkg_path, pkg_name + "."):
                try:
                    module = importlib.import_module(module_info.name)
                    if hasattr(module, class_name):
                        return getattr(module, class_name)
                    if module_info.ispkg:
                        self.find_tool(
                            class_name=class_name, package_name=module_info.name
                        )

                except (ImportError, AttributeError, ModuleNotFoundError):
                    continue
        except ImportError:
            # TODO: Need to log this error case here
            pass

        return None

    def eval_callable(
        self, callable: Callable, eval=True
    ) -> (
        BaseTool
        | tuple[
            BaseTool,
            list[Callable, typing.Iterable, dict],
            dict[str, str | Callable | typing.Iterable | dict] | None,
        ]
    ):

        if callable.args is None:
            callable.args = list()
        if callable.kwargs is None:
            callable.kwargs = dict()

        args = self.parse_entity(callable.args)
        kwargs = self.parse_entity(callable.kwargs)

        if callable.module_path is not None:
            class_ = self.import_callable(
                class_name=callable.class_name, module_path=callable.module_path
            )

        elif callable.package is not None:
            class_ = self.find_tool(callable.class_name, callable.package)
        else:
            logger.critical("package or module path not provided")
            raise Exception("package or module path not provided")

        if eval:
            return class_(*args, **kwargs)

        return class_, args, kwargs

    def parse_entity(self, entity: str | Callable | typing.Sequence | typing.Dict):
        if isinstance(entity, str):
            return entity
        if isinstance(entity, Callable):
            return self.eval_callable(entity)
        if isinstance(entity, typing.Sequence):
            return self.parse_sequence(entity)
        if isinstance(entity, typing.Dict):
            return self.parse_dict(entity)

    def parse_sequence(self, sequence: typing.Sequence) -> list:
        parsed_sequence = []
        for item in sequence:
            parsed_sequence.append(self.parse_entity(item))
        return parsed_sequence

    def parse_dict(self, dict_: typing.Dict[str, typing.Any]):
        parsed_dict = dict()
        for k, v in dict_.items():
            parsed_dict[k] = self.parse_entity(v)
        return parsed_dict
