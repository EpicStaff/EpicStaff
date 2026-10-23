"""`epicstaff-plugin verify`: say whether a package would install as Trusted or Untrusted."""

from pathlib import Path

from epicstaff_plugin.cli.output import EXIT_INVALID, EXIT_OK, UsageError, print_problems
from epicstaff_plugin.package_layout import read_package_file
from epicstaff_plugin.problems import PackageProblemsError
from epicstaff_plugin.signing import (
    InvalidPackageSignatureError,
    SignatureFormatError,
    evaluate_package_signature,
    parse_trusted_keys,
)


def verify(package_path: Path, trusted_key_entries: list[str]) -> int:
    if not package_path.is_file():
        raise UsageError(f"{package_path} is not a file")
    try:
        trusted_keys = parse_trusted_keys(trusted_key_entries)
    except SignatureFormatError as error:
        raise UsageError(f"--trusted-key {error}") from None
    try:
        package = read_package_file(package_path)
    except PackageProblemsError as error:
        print("invalid")
        print_problems(error.problems)
        return EXIT_INVALID
    manifest = package.manifest
    try:
        verdict = evaluate_package_signature(
            package.contents, manifest.id, manifest.version, package.signature, trusted_keys
        )
    except InvalidPackageSignatureError as error:
        print("invalid")
        print(f"key id: {error.key_id}")
        print(f"reason: {error}")
        return EXIT_INVALID
    print(verdict.trust)
    print(f"key id: {verdict.key_id or 'none (unsigned)'}")
    if verdict.key_name:
        print(f"key name: {verdict.key_name}")
    return EXIT_OK
