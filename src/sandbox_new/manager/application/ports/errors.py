"""Failures the venv build port reports.

A failure whose cause the adapter recognises as something the user declared raises one
of the `EnvironmentBuildError` subclasses below; their text quotes only the declared
package and specification, so it is safe to show. Any other failure raises
`EnvironmentBuildError` itself, whose text is a generic hint.
"""

from manager.domain.enums import VenvBuildErrorKind
from manager.domain.errors import BaseError

__all__ = [
    "DependencyConflictError",
    "EnvironmentBuildError",
    "PackageNotFoundError",
    "PackageVersionNotFoundError",
]


class EnvironmentBuildError(BaseError):
    code = VenvBuildErrorKind.PACKAGE_INSTALL_FAILED
    default_message: str = "Couldn't install the libraries. Check the library names and versions."


class PackageNotFoundError(EnvironmentBuildError):
    code = VenvBuildErrorKind.PACKAGE_NOT_FOUND
    default_message: str = "Package '{package}' does not exist."


class PackageVersionNotFoundError(EnvironmentBuildError):
    code = VenvBuildErrorKind.PACKAGE_VERSION_NOT_FOUND
    default_message: str = "Package '{package}' has no version matching '{specification}'."


class DependencyConflictError(EnvironmentBuildError):
    code = VenvBuildErrorKind.PACKAGE_DEPENDENCY_CONFLICT
    default_message: str = (
        "Package '{package}' requires versions of its dependencies "
        "that conflict with the other requested packages."
    )
