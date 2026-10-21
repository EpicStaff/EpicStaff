"""epicstaff_common is installed into every sandbox venv as a local package.

That the sandbox installs it unconditionally (and epicstaff_storage only for
storage jobs) is asserted by behaviour in src/sandbox/tests/chain_tests/test_predefined_libraries.py."""

import tomllib

from conftest import SHARED_DIR


def test_epicstaff_common_pyproject_is_valid_and_matches_package_dir_layout():
    pyproject_path = SHARED_DIR / "epicstaff_common" / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pyproject = tomllib.load(f)

    assert pyproject["project"]["name"] == "epicstaff-common"
    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["tool"]["setuptools"]["packages"] == ["epicstaff_common"]
    assert pyproject["tool"]["setuptools"]["package-dir"] == {"epicstaff_common": "."}
