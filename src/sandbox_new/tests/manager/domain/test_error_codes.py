"""The stable codes of the service's errors.

A code is what a client branches on when the sandbox refuses a request, and, for a venv
build error, the kind stored on the failed venv. The errors live with the contract they
belong to, so every module that defines one is imported here: a subclass is only found
once its module is loaded.
"""

import re

import pytest
from src.shared.models.code_failure import SERVER_FAILURE_CODES, CodeFailureCode

from common import public_errors
from manager.application import errors as application_errors
from manager.application.ports import errors as port_errors
from manager.domain.enums import VenvBuildErrorKind
from manager.domain import errors as domain_errors
from manager.domain.errors import BaseError


def _all_subclasses(cls: type) -> list[type]:
    found = []
    for subclass in cls.__subclasses__():
        found.append(subclass)
        found.extend(_all_subclasses(subclass))
    return found


SERVICE_ERRORS = _all_subclasses(BaseError)


@pytest.mark.parametrize("error_class", SERVICE_ERRORS, ids=lambda cls: cls.__name__)
def test_every_error_names_its_own_code(error_class):
    # Its own, not inherited: a subclass that inherited its parent's code would answer
    # with a failure name that isn't its own.
    assert "code" in vars(error_class)
    assert re.fullmatch(r"[a-z]+(_[a-z]+)*", error_class.code)


def test_no_two_errors_share_a_code():
    codes = [error_class.code for error_class in SERVICE_ERRORS]

    assert len(codes) == len(set(codes))


PINNED_CODES = {
    application_errors.VenvNotFoundError: "venv_not_found",
    application_errors.ExecutionNotFoundError: "execution_not_found",
    application_errors.SandboxOverloadedError: "sandbox_overloaded",
    port_errors.EnvironmentBuildError: "package_install_failed",
    port_errors.PackageNotFoundError: "package_not_found",
    port_errors.PackageVersionNotFoundError: "package_version_not_found",
    port_errors.DependencyConflictError: "package_dependency_conflict",
    domain_errors.NotFoundError: "not_found",
    domain_errors.ConflictError: "conflict",
    domain_errors.BadRequestError: "bad_request",
    domain_errors.CustomLibraryNotFoundError: "custom_library_not_found",
    domain_errors.CustomLibraryNameNotFoundError: "custom_library_name_not_found",
    domain_errors.CustomLibraryNotPublishedError: "custom_library_not_published",
    domain_errors.CustomLibraryStillBuildingError: "custom_library_still_building",
    domain_errors.WheelNotFoundError: "wheel_not_found",
    domain_errors.CustomLibraryNameTakenError: "custom_library_name_taken",
    domain_errors.WheelVersionTakenError: "wheel_version_taken",
    domain_errors.WheelSourceAlreadyUploadedError: "wheel_source_already_uploaded",
    domain_errors.CustomLibraryInUseError: "custom_library_in_use",
    domain_errors.WheelInUseError: "wheel_in_use",
    domain_errors.WheelNotBuiltError: "wheel_not_built",
    domain_errors.UnsupportedUploadError: "unsupported_upload",
    domain_errors.WheelNameMismatchError: "wheel_name_mismatch",
}


@pytest.mark.parametrize(
    ("error_class", "code"), PINNED_CODES.items(), ids=lambda value: getattr(value, "__name__", value)
)
def test_codes_stay_stable(error_class, code):
    assert error_class.code == code


def test_every_error_has_its_code_pinned():
    assert set(SERVICE_ERRORS) == set(PINNED_CODES)


@pytest.mark.parametrize("kind", list(VenvBuildErrorKind), ids=str)
def test_every_venv_build_error_kind_is_a_code_failure_code(kind):
    # A job whose venv failed to build reports the kind as its failure's code.
    assert CodeFailureCode(kind.value) == kind.value


def test_the_sandbox_has_a_text_for_every_failure_only_its_log_explains():
    assert set(public_errors._PUBLIC_TEXTS) == SERVER_FAILURE_CODES
