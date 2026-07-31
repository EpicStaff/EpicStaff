import inspect
import pytest

from computers import Computer, default, contrib


def get_module_classes(module):
    # Grab classes actually defined in that module and subclassing Computer.
    return [obj for _, obj in inspect.getmembers(module, inspect.isclass)]


def get_required_attrs():
    # TODO: migrate to a cleaner solution that allows type-checking (e.g. pydantic?)
    return [
        name
        for name, member in inspect.getmembers(Computer)
        if not name.startswith("__")
        and (inspect.isfunction(member) or isinstance(member, property))
    ]


default_computers = get_module_classes(default)
contrib_computers = get_module_classes(contrib)
all_computers = default_computers + contrib_computers


@pytest.mark.parametrize("computer_class", all_computers, ids=lambda c: c.__name__)
def test_computer_implements_interface(computer_class):
    for func in get_required_attrs():
        assert hasattr(
            computer_class, func
        ), f"{computer_class.__name__} is missing required attribute '{func}'"
