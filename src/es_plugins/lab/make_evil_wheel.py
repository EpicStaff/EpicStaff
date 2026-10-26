"""Writes the node lab's hostile wheels: what a plugin could ship to run as the node agent.

- `evil-1.0-py3-none-any.whl` holds a root `evil.pth`, whose import line runs on every start of
  the venv's interpreter, and `.data/scripts/python` and `python3`, which pip installs over the
  venv's own.
- `evil_pip-1.0-py3-none-any.whl` holds files at pip's own paths (`pip/__init__.py`,
  `pip/_internal/cli/main.py`, ...): a pip that ran from the venv's site-packages would import
  them as the agent once they were installed over it.

Each file leaves a `*-ran-as-<uid>` file where it can write, so the lab sees whether the agent
(UID 10000), or anyone, ever ran it. Usage: python make_evil_wheel.py <output directory>
"""

import base64
import hashlib
import sys
import zipfile
from pathlib import Path


def marker_writer(name: str) -> str:
    """Python that leaves `<name>-ran-as-<uid>` in TMPDIR and HOME, where it can write."""
    return (
        "import os, pathlib; [pathlib.Path(directory, f'"
        + name
        + "-ran-as-{os.getuid()}').write_text('ran')"
        " for directory in {os.environ.get('TMPDIR', '/tmp'), os.environ.get('HOME', '/tmp')}"
        " if os.access(directory, os.W_OK)]\n"
    )


REPLACED_PYTHON = (
    "#!/bin/sh\n"
    'touch "${TMPDIR:-/tmp}/replaced-python-ran-as-$(id -u)"\n'
    'exec /usr/local/bin/python3 "$@"\n'
)
PIP_PATHS = (
    "pip/__init__.py",
    "pip/__main__.py",
    "pip/_internal/__init__.py",
    "pip/_internal/cli/__init__.py",
    "pip/_internal/cli/main.py",
    "pip/_internal/operations/__init__.py",
    "pip/_internal/operations/install/__init__.py",
    "pip/_internal/operations/install/wheel.py",
    "pip/_internal/utils/__init__.py",
    "pip/_internal/utils/misc.py",
)


def wheel_metadata(name: str, distribution: str) -> dict[str, str]:
    return {
        f"{distribution}-1.0.dist-info/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n",
        f"{distribution}-1.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\nGenerator: es-plugins-lab\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }


WHEELS = {
    "evil": {
        "evil/__init__.py": "",
        "evil.pth": marker_writer("pth"),
        "evil-1.0.data/scripts/python": REPLACED_PYTHON,
        "evil-1.0.data/scripts/python3": REPLACED_PYTHON,
        **wheel_metadata("evil", "evil"),
    },
    "evil_pip": {
        **{path: marker_writer("pip") for path in PIP_PATHS},
        **wheel_metadata("evil-pip", "evil_pip"),
    },
}


def record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def write_wheel(output: Path, distribution: str, files: dict[str, str]) -> Path:
    record = [record_line(path, text.encode()) for path, text in files.items()]
    record.append(f"{distribution}-1.0.dist-info/RECORD,,")
    wheel = output / f"{distribution}-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
        archive.writestr(f"{distribution}-1.0.dist-info/RECORD", "\n".join(record) + "\n")
    return wheel


def main() -> None:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    for distribution, files in WHEELS.items():
        print(write_wheel(output, distribution, files))


if __name__ == "__main__":
    main()
