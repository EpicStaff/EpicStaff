import logging

logger = logging.getLogger(__name__)
logger.debug(f"Entered {__file__}")
import pkgutil
import importlib

logger = logging.getLogger(__name__)
logger.debug(f"Entered the module {__file__}")
# from utils.helpers import load_env
# load_env("../../ENV/.env", ["OPENAI_API_KEY","OPENAI_BASE_URL"])


def import_package_modules(package, modules_list, integration_dict, recursive=False):
    """
    Dynamically imports all submodules from the specified package, appends them to modules_list,
    and populates an integration dictionary with all public members of the modules.

    Args:
        package (module): The package from which to import all submodules.
        modules_list (list): List to which module references will be appended.
        integration_dict (dict): Dictionary to which public module members are added.
        recursive (bool): If True, imports submodules recursively.

    Returns:
        None: Modifies modules_list and integration_dict in-place.
    """
    package_path = package.__path__  # This gets the package path iterable
    package_name = package.__name__  # Get the full package name

    # Iterate through the package modules
    for loader, name, ispkg in pkgutil.walk_packages(
        package_path, prefix=package_name + "."
    ):
        try:
            module = importlib.import_module(name)
            modules_list.append((module, name))
            # Integrate public members, irrespective of whether the module is a package
            for attr_name in dir(module):
                if not attr_name.startswith("_"):  # Include only public members
                    obj = getattr(module, attr_name)
                    integration_dict[attr_name] = obj

            logger.info(f"Imported and added module: {name}")
            # Recursively import submodules if it is a package and recursive is True
            if recursive and ispkg:
                import_package_modules(
                    module, modules_list, integration_dict, recursive=True
                )
        except ImportError as e:
            logger.warning(f"Failed to import {name}: {e}")
