"""`epicstaff-plugin validate`: check a plugin source directory or a built package."""

from pathlib import Path

from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.package_layout import read_package_file
from epicstaff_plugin.package_source import collect_source
from epicstaff_plugin.problems import PackageProblemsError


def validate(target: Path, spa_directory: Path | None) -> int:
    if target.is_file():
        if spa_directory is not None:
            raise UsageError("--spa-dir applies to a source directory, not to a built package")
        return _validate_package(target)
    if target.is_dir():
        return _validate_source(target, spa_directory)
    raise UsageError(f"{target} is neither a directory nor a file")


def _validate_package(path: Path) -> int:
    try:
        package = read_package_file(path)
    except PackageProblemsError as error:
        print_problems(error.problems)
        return EXIT_INVALID
    signature = "present" if package.signature else "absent"
    print(f"valid: {package.manifest.id} {package.manifest.version} (signature {signature})")
    return EXIT_OK


def _validate_source(directory: Path, spa_directory: Path | None) -> int:
    try:
        source = collect_source(directory, spa_directory)
    except PackageProblemsError as error:
        print_problems(error.problems)
        return EXIT_INVALID
    problems = source.problems(source.describe())
    if problems:
        print_problems(problems)
        return EXIT_INVALID
    if source.manifest.spa is not None and not source.includes_spa:
        print("note: the single-page app was not checked; pass the built app with --spa-dir")
    print(f"valid: {source.manifest.id} {source.manifest.version} (source)")
    return EXIT_OK
