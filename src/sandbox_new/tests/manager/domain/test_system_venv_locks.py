"""The image's system-venv lock files hold exactly the pins SYSTEM_VENV_LIBS asks for.

The manager builds the system venvs at startup from the wheels these files bring into the
image, with no package index. A pin changed in SYSTEM_VENV_LIBS without regenerating the
files (`make uv-lock-system-venvs`) would leave the wheel out of the image and stop a
sandbox without internet from starting; the image build catches it too, this catches it
before.
"""

from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from manager.domain.models import SYSTEM_VENV_LIBS

LOCK_DIR = Path(__file__).resolve().parents[3] / "system-venv-requirements"
KEYS_WITH_LIBRARIES = [key for key, libraries in SYSTEM_VENV_LIBS.items() if libraries]


def locked_pins(lock_file: Path) -> dict[str, str]:
    """Package name -> pinned version, from the requirement lines of a uv lock."""
    pins: dict[str, str] = {}
    for line in lock_file.read_text().splitlines():
        if not line or line[0] in " #":
            continue
        requirement = Requirement(line.rstrip(" \\"))
        pins[canonicalize_name(requirement.name)] = str(requirement.specifier)
    return pins


@pytest.mark.parametrize("system_key", KEYS_WITH_LIBRARIES)
def test_the_lock_pins_every_library_at_the_version_the_system_venv_asks_for(system_key):
    pins = locked_pins(LOCK_DIR / f"{system_key}.txt")

    for library in SYSTEM_VENV_LIBS[system_key]:
        # The lock pins the package; extras such as `[binary]` only add dependencies.
        package = canonicalize_name(Requirement(library.name).name)
        assert pins.get(package) == library.specification, library.name


def test_there_is_a_lock_for_each_system_venv_with_libraries_and_no_other():
    assert sorted(path.stem for path in LOCK_DIR.glob("*.txt")) == sorted(KEYS_WITH_LIBRARIES)
