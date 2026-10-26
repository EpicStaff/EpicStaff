"""`epicstaff-plugin validate`: check a plugin source directory or a built package."""

from pathlib import Path

from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.package_layout import BACKEND_REQUIREMENTS, read_package_file
from epicstaff_plugin.package_source import PackageSource, collect_source
from epicstaff_plugin.problems import PackageProblemsError
from epicstaff_plugin.requirements_lock import SDK_DISTRIBUTION, parse_requirements_lock


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
    # The SDK wheel may be added by `pack --local-wheel`; a built package must pin it.
    problems = source.problems(source.describe(), require_sdk_pin=False)
    if problems:
        print_problems(problems)
        return EXIT_INVALID
    if source.manifest.spa is not None and not source.includes_spa:
        print("note: the single-page app was not checked; pass the built app with --spa-dir")
    if source.manifest.backend is not None and not _pins_sdk(source):
        print(
            f"note: {BACKEND_REQUIREMENTS} does not pin {SDK_DISTRIBUTION}; "
            "pack with --local-wheel <epicstaff-plugin wheel> to add it"
        )
    print(f"valid: {source.manifest.id} {source.manifest.version} (source)")
    return EXIT_OK


def _pins_sdk(source: PackageSource) -> bool:
    # Only reached once the source passed every check, so the lock exists and parses.
    lock = parse_requirements_lock(source.file(BACKEND_REQUIREMENTS).source.read_bytes())
    return bool(lock.pins(SDK_DISTRIBUTION))
