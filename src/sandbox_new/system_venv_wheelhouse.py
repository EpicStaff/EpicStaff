"""Pins and checks the wheels the system venvs are built from, so the image needs no index.

The manager builds every system venv (`SYSTEM_VENV_LIBS`) at startup and will not start
while one fails, so their libraries ship inside the image like the predefined packages:

    lock                Write system-venv-requirements/<key>.txt, every dependency pinned
                        by hash, from the pins in SYSTEM_VENV_LIBS. Needs the package index;
                        run it (`make uv-lock-system-venvs`) after changing a pin.
    check WHEELHOUSE    Build each system venv from WHEELHOUSE alone, through the same
                        UVProvider call the manager makes at startup. Dockerfile.manager runs
                        it, so a pin changed without a new lock fails the image build instead
                        of the start of a sandbox without internet.

Run from src/sandbox_new, with the sandbox's own interpreter.
"""

import asyncio
import subprocess
import sys
import tempfile
from pathlib import Path

from manager.domain.models import SYSTEM_VENV_LIBS
from manager.infrastructure.providers.uv_provider import UVProvider

LOCK_DIR = Path(__file__).resolve().parent / "system-venv-requirements"


def requirements(system_key: str) -> list[str]:
    return [library.requirement for library in SYSTEM_VENV_LIBS[system_key]]


def keys_with_libraries() -> list[str]:
    """The system venvs that install anything: one with no libraries needs no wheels."""
    return [system_key for system_key in SYSTEM_VENV_LIBS if requirements(system_key)]


def lock() -> None:
    # One file per venv, not one for all: their pins are resolved apart at runtime,
    # and one resolution for all of them could fail on a conflict no single venv has.
    LOCK_DIR.mkdir(exist_ok=True)
    for system_key in keys_with_libraries():
        subprocess.run(
            [
                "uv",
                "pip",
                "compile",
                "--quiet",
                "--no-config",
                "--universal",
                "--python-version",
                "3.12",
                "--generate-hashes",
                # The pins come in on stdin, so the header names the target to rerun.
                "--custom-compile-command",
                "make uv-lock-system-venvs",
                "-",
                "--output-file",
                str(LOCK_DIR / f"{system_key}.txt"),
            ],
            input="\n".join(requirements(system_key)),
            text=True,
            check=True,
        )
        print(f"Locked the {system_key} venv")


async def check(wheelhouse: Path) -> int:
    failed = []
    with tempfile.TemporaryDirectory() as root:
        for system_key in keys_with_libraries():
            venv_path = Path(root) / system_key
            try:
                await UVProvider.init_venv(venv_path)
                await UVProvider.apply(
                    venv_path, *requirements(system_key), wheelhouse=wheelhouse, offline=True
                )
            except Exception as error:
                failed.append(system_key)
                print(f"The {system_key} venv cannot be built offline: {error}", file=sys.stderr)
            else:
                print(f"The {system_key} venv builds offline")
    if failed:
        print(
            f"Missing wheels for {', '.join(failed)}: run `make uv-lock-system-venvs` "
            "after changing SYSTEM_VENV_LIBS.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    command = sys.argv[1:2]
    if command == ["lock"]:
        lock()
    elif command == ["check"] and len(sys.argv) == 3:
        sys.exit(asyncio.run(check(Path(sys.argv[2]))))
    else:
        sys.exit(__doc__)
