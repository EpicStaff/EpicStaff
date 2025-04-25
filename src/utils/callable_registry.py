import logging

logger = logging.getLogger(__name__)
from config.config import ToolsConfig
import inspect

callables_list = ToolsConfig.callables_list
modules_list = ToolsConfig.modules_list


class CallableRegistry:
    _instance = None  # Singleton

    def __new__(cls):
        """Implement Singleton pattern. Only one instance of this class is created."""
        if cls._instance is None:
            cls._instance = super(CallableRegistry, cls).__new__(cls)
            cls._instance.callable_dict = {}
            cls._instance.simple_name_dict = {}
            cls._instance.register_modules(modules_list)
            cls._instance.register_callables(callables_list)
        return cls._instance

    def register_modules(self, modules_list):
        """Registers all methods, functions, and classes from specified modules."""
        for module, alias in modules_list:

            for name, obj in inspect.getmembers(
                module, predicate=lambda x: callable(x) or inspect.isclass(x)
            ):
                qualified_name = f"{alias}.{name}"
                self._register_callable(name, qualified_name, obj)
                logger.info(f"Registered {qualified_name} as callable.")

    def register_callables(
        self, callables_list
    ):  # e.gg loat_tools is not callable without parameters
        """Registers specific callables provided in a list."""
        for callable_item in callables_list:
            try:
                if callable(callable_item):
                    callable_name = getattr(
                        callable_item, "__name__", type(callable_item).__name__
                    )
                    callable_module = getattr(
                        callable_item, "__module__", "unknown_module"
                    )
                    qualified_name = f"{callable_module}.{callable_name}"
                    self._register_callable(
                        callable_name, qualified_name, callable_item
                    )
            except AttributeError as e:
                logging.error(f"Failed to register {callable_item}: {str(e)}")

    def _register_callable(self, name, qualified_name, callable_item):
        """Helper method to register a callable under both its full and simple names."""
        self.callable_dict[qualified_name] = callable_item
        if name in self.simple_name_dict:
            # Handle name collisions: store multiple callables under the same simple name in a list
            if isinstance(self.simple_name_dict[name], list):
                self.simple_name_dict[name].append(callable_item)
            else:
                self.simple_name_dict[name] = [
                    self.simple_name_dict[name],
                    callable_item,
                ]
        else:
            self.simple_name_dict[name] = callable_item
        logger.info(f"Successfully registered callable: {qualified_name} as '{name}'.")

    def get_callable(self, name):
        """Retrieves a callable by its full name or simple name."""
        if name in self.callable_dict:
            return self.callable_dict[name]
        elif name in self.simple_name_dict:
            result = self.simple_name_dict[name]
            if isinstance(result, list):
                logging.warning(
                    f"Multiple callables found for '{name}'. Returning the first one."
                )
                return result[0]  # Return the first callable from the list
            return result
        return None
