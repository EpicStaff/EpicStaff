import subprocess
import sys
from pathlib import Path

PACKAGE_DIRECTORY = Path(__file__).resolve().parents[1]
HEAVY_MODULES = {"ast", "dataclasses", "inspect", "typing"}


def test_import_loads_no_heavy_modules():
    # -S: site and .pth files may import these themselves, the sandbox child's wouldn't matter.
    loaded = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            "import sys; import dotdict; print(' '.join(sorted(sys.modules)))",
        ],
        cwd=PACKAGE_DIRECTORY,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()

    assert HEAVY_MODULES.isdisjoint(loaded)
