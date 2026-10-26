"""Check a downloaded package before anything of it is unpacked.

The download's sha256 has already matched the desired state. On top of that the node
applies the same package rules EpicStaff applied at upload (`epicstaff_plugin.package_layout`:
every file listed in `CONTENTS.json` with its size and sha256, nothing unlisted, the fixed
layout), checks that the manifest is the one the desired state describes, and, for a
Trusted package, verifies the signature against the key named in the desired state.
"""

from pathlib import Path

from epicstaff_plugin.package_layout import PackageArchive, read_package_file
from epicstaff_plugin.problems import PackageProblemsError
from epicstaff_plugin.signing import (
    InvalidPackageSignatureError,
    PublicKey,
    SignatureFormatError,
    TrustedKey,
    evaluate_package_signature,
)
from src.shared.models.plugin_nodes import DesiredPackage, DesiredRuntime

_PROBLEMS_SHOWN = 5


class PackageVerificationError(Exception):
    """The package is not the one the desired state names, or breaks a package rule."""


def verify_package(
    path: Path, plugin: str, package: DesiredPackage, runtime: DesiredRuntime
) -> PackageArchive:
    """Return the checked package: `plugin`'s `package`, to run with `runtime`.

    The desired placement's package and runtime, or an upgrade's target and its runtime.
    CPU-bound: run it in a worker thread.

    Raises:
        PackageVerificationError: Any check fails; the message says which.
    """
    try:
        archive = read_package_file(path)
    except PackageProblemsError as error:
        shown = "; ".join(
            f"{problem.loc}: {problem.message}" for problem in error.problems[:_PROBLEMS_SHOWN]
        )
        raise PackageVerificationError(f"the package breaks the package rules: {shown}") from None
    _check_manifest(archive, plugin, package, runtime)
    if package.trust == "trusted":
        _check_signature(archive, package)
    return archive


def _check_manifest(
    archive: PackageArchive, plugin: str, package: DesiredPackage, runtime: DesiredRuntime
) -> None:
    manifest = archive.manifest
    expected = {
        "id": (manifest.id, plugin),
        "version": (manifest.version, package.version),
        "backend.python": (manifest.backend.python if manifest.backend else None, runtime.python),
        "backend.entrypoint": (
            manifest.backend.entrypoint if manifest.backend else None,
            runtime.entrypoint,
        ),
    }
    for field, (found, wanted) in expected.items():
        if found != wanted:
            raise PackageVerificationError(
                f"the package's manifest has {field} {found!r}, the desired state {wanted!r}"
            )


def _check_signature(archive: PackageArchive, package: DesiredPackage) -> None:
    key_text = package.signer_public_key
    if not key_text:
        raise PackageVerificationError("the package is Trusted but no signer key was sent")
    try:
        signer = TrustedKey(name="signer", public_key=PublicKey.from_text(key_text))
        verdict = evaluate_package_signature(
            archive.contents,
            archive.manifest.id,
            archive.manifest.version,
            archive.signature,
            [signer],
        )
    except (SignatureFormatError, InvalidPackageSignatureError) as error:
        raise PackageVerificationError(f"the package's signature is invalid: {error}") from None
    if verdict.trust != "trusted":
        reason = (
            "has no signature"
            if verdict.signature == "absent"
            else f"is signed by key {verdict.key_id}, not by {signer.public_key.display_id}"
        )
        raise PackageVerificationError(f"the package is Trusted but {reason}")
