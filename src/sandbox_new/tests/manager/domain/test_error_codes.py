"""The codes a client branches on when the sandbox refuses or fails a request."""

import re

import pytest

from manager.domain import errors
from manager.domain.errors import BaseError


def _all_subclasses(cls: type) -> list[type]:
    found = []
    for subclass in cls.__subclasses__():
        found.append(subclass)
        found.extend(_all_subclasses(subclass))
    return found


DOMAIN_ERRORS = _all_subclasses(BaseError)


@pytest.mark.parametrize("error_class", DOMAIN_ERRORS, ids=lambda cls: cls.__name__)
def test_every_domain_error_names_its_own_code(error_class):
    # Its own, not inherited: a subclass that inherited its parent's code would answer
    # with a failure name that isn't its own.
    assert "code" in vars(error_class)
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", error_class.code)


def test_no_two_domain_errors_share_a_code():
    codes = [error_class.code for error_class in DOMAIN_ERRORS]

    assert len(codes) == len(set(codes))


@pytest.mark.parametrize(
    ("error_class", "code"),
    [
        (errors.VenvNotFoundError, "venv_not_found"),
        (errors.ExecutionNotFoundError, "execution_not_found"),
        (errors.SandboxOverloadedError, "sandbox_overloaded"),
        (errors.UVBuildError, "package_install_failed"),
        (errors.UVPackageNotFoundError, "package_not_found"),
        (errors.UVVersionNotFoundError, "package_version_not_found"),
        (errors.UVDependencyResolutionError, "package_dependency_conflict"),
    ],
)
def test_codes_stay_stable(error_class, code):
    assert error_class.code == code
