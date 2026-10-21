"""Writes the node lab's hostile wheel: what a plugin could ship to run as the node agent.

`evil-1.0-py3-none-any.whl` holds a root `evil.pth`, whose import line runs on every start of
the venv's interpreter, and `.data/scripts/python` and `python3`, which pip installs over the
venv's own. Each leaves a `*-ran-as-<uid>` file where it can write, so the lab sees whether the
agent (UID 10000) ever ran either. Usage: python make_evil_wheel.py <output directory>
"""

import base64
import hashlib
import sys
import zipfile
from pathlib import Path

PTH = (
    "import os, pathlib; [pathlib.Path(directory, f'pth-ran-as-{os.getuid()}').write_text('ran')"
    " for directory in {os.environ.get('TMPDIR', '/tmp'), os.environ.get('HOME', '/tmp')}"
    " if os.access(directory, os.W_OK)]\n"
)
REPLACED_PYTHON = (
    "#!/bin/sh\n"
    'touch "${TMPDIR:-/tmp}/replaced-python-ran-as-$(id -u)"\n'
    'exec /usr/local/bin/python3 "$@"\n'
)
FILES = {
    "evil/__init__.py": "",
    "evil.pth": PTH,
    "evil-1.0.data/scripts/python": REPLACED_PYTHON,
    "evil-1.0.data/scripts/python3": REPLACED_PYTHON,
    "evil-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: evil\nVersion: 1.0\n",
    "evil-1.0.dist-info/WHEEL": (
        "Wheel-Version: 1.0\nGenerator: es-plugins-lab\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    ),
}


def record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def main() -> None:
    output = Path(sys.argv[1])
    output.mkdir(parents=True, exist_ok=True)
    record = [record_line(path, text.encode()) for path, text in FILES.items()]
    record.append("evil-1.0.dist-info/RECORD,,")
    wheel = output / "evil-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in FILES.items():
            archive.writestr(path, text)
        archive.writestr("evil-1.0.dist-info/RECORD", "\n".join(record) + "\n")
    print(wheel)


if __name__ == "__main__":
    main()
