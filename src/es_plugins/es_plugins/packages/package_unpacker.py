import hashlib
import shutil
import zipfile
from pathlib import Path

from epicstaff_plugin.package_layout import BACKEND_DIRECTORY, PackageArchive
from epicstaff_plugin.paths import path_problem

from es_plugins.packages.package_verifier import PackageVerificationError

_CHUNK_BYTES = 1024 * 1024


def unpack_backend(package_path: Path, archive: PackageArchive, destination: Path) -> None:
    """Extract the `backend/` files of a verified package into a fresh `destination`.

    Only files `CONTENTS.json` lists are written, each checked again against its listed size
    and sha256 as it is extracted. CPU- and disk-bound: run it in a worker thread.

    Raises:
        PackageVerificationError: A file differs from its listing.
    """
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    with zipfile.ZipFile(package_path) as package:
        for listed in archive.files:
            if not listed.path.startswith(BACKEND_DIRECTORY):
                continue
            # The archive reader refused such paths already; a second look costs nothing.
            if problem := path_problem(listed.path):
                raise PackageVerificationError(f"the path {listed.path!r} {problem}")
            target = destination / listed.path
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            with package.open(listed.path) as member, open(target, "xb") as extracted:
                while chunk := member.read(_CHUNK_BYTES):
                    size += len(chunk)
                    if size > listed.size:
                        break
                    digest.update(chunk)
                    extracted.write(chunk)
            if size != listed.size or digest.hexdigest() != listed.sha256:
                raise PackageVerificationError(f"{listed.path} does not match CONTENTS.json")
